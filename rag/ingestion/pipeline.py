from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Protocol

from opentelemetry import trace

from rag.ingestion.chunk import Chunk
from rag.ingestion.fingerprint import content_fingerprint
from rag.ingestion.manifest import load_manifest
from rag.ingestion.models import ManifestDocument
from rag.ingestion.parse import extract_pdf_pages
from rag.ingestion.payload import build_qdrant_payload
from rag.ingestion.sparse import SparseVectorData
from rag.ingestion.store import object_key_for


EMBEDDING_DIMENSIONS = 1536
PIPELINE_REVISION = "rag-ingestion-v2"
VECTOR_SCHEMA_REVISION = "dense-1536-sparse-bm25-v1"


@dataclass(frozen=True)
class DocumentState:
    fingerprint: str
    chunk_ids: tuple[str, ...]
    object_key: str


@dataclass(frozen=True)
class IngestionSummary:
    docs_seen: int
    docs_changed: int
    chunks_written: int


@dataclass(frozen=True)
class _PreparedDocument:
    document: ManifestDocument
    chunks: list[Chunk]
    fingerprint: str
    object_key: str
    prior_state: DocumentState | None
    registry_matches: bool
    point_ids_match: bool
    existing_point_ids: set[str]
    payloads: list[dict[str, str | int | None]]
    pdf_exists: bool


class Registry(Protocol):
    def locked(self) -> AbstractContextManager[None]: ...
    def start_run(self, docs_seen: int) -> str: ...
    def get_document(self, document_id: str) -> DocumentState | None: ...
    def replace_document(
        self,
        document: ManifestDocument,
        chunks: list[Chunk],
        fingerprint: str,
        embedding_model: str,
        object_key: str,
    ) -> None: ...
    def finish_run(
        self,
        run_id: str,
        docs_seen: int,
        docs_changed: int,
        chunks_written: int,
    ) -> None: ...
    def fail_run(self, run_id: str, error_category: str) -> None: ...


class PdfStore(Protocol):
    def ensure_bucket(self) -> None: ...
    def exists(self, object_key: str) -> bool: ...
    def upload(self, document: ManifestDocument, object_key: str) -> None: ...


class VectorStore(Protocol):
    def ensure_collection(self) -> None: ...
    def document_point_ids(self, document_id: str) -> set[str]: ...
    def point_ids_match(
        self,
        point_ids: list[str],
        payloads: list[dict[str, str | int | None]],
    ) -> set[str]: ...
    def upsert(
        self,
        point_ids: list[str],
        vectors: list[list[float]],
        sparse_vectors: list[SparseVectorData],
        payloads: list[dict[str, Any]],
    ) -> None: ...
    def delete(self, point_ids: list[str]) -> None: ...


class Embedder(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...


class SparseEmbedder(Protocol):
    model_name: str

    def embed_passages(self, texts: list[str]) -> list[SparseVectorData]: ...


def _prepare_document(
    document: ManifestDocument,
    *,
    registry: Registry,
    pdf_store: PdfStore,
    vector_store: VectorStore,
    embedding_model: str,
    sparse_model: str,
) -> _PreparedDocument:
    tracer = trace.get_tracer(__name__)
    document_id = str(document.metadata["doc_id"])
    with tracer.start_as_current_span("rag.parse") as span:
        pages = extract_pdf_pages(document.pdf_path)
        span.set_attribute("rag.page_count", len(pages))
    with tracer.start_as_current_span("rag.chunk") as span:
        chunks = chunk_document(document_id, pages)
        span.set_attribute("rag.chunk_count", len(chunks))
    fingerprint = content_fingerprint(
        document,
        pipeline_revision=PIPELINE_REVISION,
        embedding_model=embedding_model,
        vector_schema_revision=VECTOR_SCHEMA_REVISION,
        sparse_model=sparse_model,
    )
    object_key = object_key_for(document)
    prior_state = registry.get_document(document_id)
    chunk_ids = [chunk.chunk_id for chunk in chunks]
    existing_point_ids = vector_store.document_point_ids(document_id)
    payloads = [build_qdrant_payload(document, chunk, fingerprint) for chunk in chunks]
    registry_matches = (
        prior_state is not None
        and prior_state.fingerprint == fingerprint
        and set(prior_state.chunk_ids) == set(chunk_ids)
        and prior_state.object_key == object_key
    )
    point_ids_match = (
        vector_store.point_ids_match(chunk_ids, payloads) == set(chunk_ids)
        and existing_point_ids == set(chunk_ids)
    )
    return _PreparedDocument(
        document=document,
        chunks=chunks,
        fingerprint=fingerprint,
        object_key=object_key,
        prior_state=prior_state,
        registry_matches=registry_matches,
        point_ids_match=point_ids_match,
        existing_point_ids=existing_point_ids,
        payloads=payloads,
        pdf_exists=pdf_store.exists(object_key),
    )


def chunk_document(document_id: str, pages: list[Any]) -> list[Chunk]:
    from rag.ingestion.chunk import chunk_pages

    return chunk_pages(document_id, pages)


def ingest_documents(
    documents: list[ManifestDocument],
    *,
    registry: Registry,
    pdf_store: PdfStore,
    vector_store: VectorStore,
    embedder: Embedder,
    sparse_embedder: SparseEmbedder | None = None,
    embedding_model: str = "embed-small",
    sparse_model: str = "Qdrant/bm25",
) -> IngestionSummary:
    """Reconcile a manifest across MinIO, Qdrant, and Postgres; retries converge."""
    if not documents:
        raise ValueError("ingestion manifest contains no documents")
    ids = [str(document.metadata["doc_id"]) for document in documents]
    if len(ids) != len(set(ids)):
        raise ValueError("ingestion manifest contains duplicate document IDs")
    if sparse_embedder is None:
        candidate = getattr(embedder, "embed_passages", None)
        if not callable(candidate):
            raise ValueError("a sparse embedder is required")
        sparse_embedder = embedder  # type: ignore[assignment]

    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("rag.ingest") as root_span:
        root_span.set_attribute("rag.docs_seen", len(documents))
        with registry.locked():
            run_id = registry.start_run(len(documents))
            try:
                vector_store.ensure_collection()
                pdf_store.ensure_bucket()
                prepared = [
                    _prepare_document(
                        document,
                        registry=registry,
                        pdf_store=pdf_store,
                        vector_store=vector_store,
                        embedding_model=embedding_model,
                        sparse_model=sparse_model,
                    )
                    for document in documents
                ]
                requiring_vectors = [
                    item
                    for item in prepared
                    if not item.registry_matches or not item.point_ids_match
                ]
                texts = [chunk.text for item in requiring_vectors for chunk in item.chunks]
                with tracer.start_as_current_span("rag.embed") as span:
                    span.set_attribute("gen_ai.request.model", embedding_model)
                    span.set_attribute("rag.chunk_count", len(texts))
                    vectors = embedder.embed_texts(texts) if texts else []
                    if len(vectors) != len(texts):
                        raise ValueError("embedding response count does not match chunk count")
                    if any(len(vector) != EMBEDDING_DIMENSIONS for vector in vectors):
                        raise ValueError("embedding vector dimension does not match 1536")
                    span.set_attribute("rag.vector_count", len(vectors))

                with tracer.start_as_current_span("rag.sparse_embed") as span:
                    span.set_attribute("rag.sparse_model", sparse_model)
                    span.set_attribute("rag.chunk_count", len(texts))
                    sparse_vectors = sparse_embedder.embed_passages(texts)
                    if len(sparse_vectors) != len(texts):
                        raise ValueError("sparse embedding count does not match chunk count")
                    span.set_attribute("rag.sparse_vector_count", len(sparse_vectors))

                vector_offset = 0
                docs_changed = 0
                chunks_written = 0
                for item in prepared:
                    needs_vectors = not item.registry_matches or not item.point_ids_match
                    needs_registry = not item.registry_matches
                    needs_pdf = not item.pdf_exists or not item.registry_matches
                    if not (needs_vectors or needs_registry or needs_pdf):
                        continue
                    docs_changed += 1
                    if needs_pdf:
                        with tracer.start_as_current_span("rag.store"):
                            pdf_store.upload(item.document, item.object_key)

                    if needs_vectors:
                        count = len(item.chunks)
                        document_vectors = vectors[vector_offset : vector_offset + count]
                        document_sparse_vectors = sparse_vectors[
                            vector_offset : vector_offset + count
                        ]
                        vector_offset += count
                        with tracer.start_as_current_span("rag.store"):
                            vector_store.upsert(
                                [chunk.chunk_id for chunk in item.chunks],
                                document_vectors,
                                document_sparse_vectors,
                                item.payloads,
                            )
                        chunks_written += count

                    desired_ids = {chunk.chunk_id for chunk in item.chunks}
                    prior_ids = set(item.prior_state.chunk_ids) if item.prior_state else set()
                    stale_ids = sorted((prior_ids | item.existing_point_ids) - desired_ids)
                    if stale_ids:
                        with tracer.start_as_current_span("rag.store"):
                            vector_store.delete(stale_ids)

                    if needs_registry:
                        registry.replace_document(
                            item.document,
                            item.chunks,
                            item.fingerprint,
                            embedding_model,
                            item.object_key,
                        )

                summary = IngestionSummary(
                    docs_seen=len(documents),
                    docs_changed=docs_changed,
                    chunks_written=chunks_written,
                )
                registry.finish_run(
                    run_id,
                    summary.docs_seen,
                    summary.docs_changed,
                    summary.chunks_written,
                )
                root_span.set_attribute("rag.docs_changed", docs_changed)
                root_span.set_attribute("rag.chunks_written", chunks_written)
                return summary
            except Exception as error:
                registry.fail_run(run_id, type(error).__name__)
                root_span.set_attribute("error.type", type(error).__name__)
                raise