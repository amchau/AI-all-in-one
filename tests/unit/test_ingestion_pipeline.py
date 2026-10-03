from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Iterator
from unittest.mock import patch

import pytest

from rag.ingestion.manifest import load_manifest
from rag.ingestion.models import Chunk, ManifestDocument, PageText
from rag.ingestion.pipeline import DocumentState, IngestionSummary, ingest_documents
from rag.ingestion.store import object_key_for


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
GENERATED_DIR = REPOSITORY_ROOT / "data" / "generated"


class FakeRegistry:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, object]] = {}
        self.runs: dict[str, str] = {}
        self.replace_calls = 0
        self.fail_replace_once = False

    @contextmanager
    def locked(self) -> Iterator[None]:
        yield

    def start_run(self, docs_seen: int) -> str:
        run_id = f"run-{len(self.runs) + 1}"
        self.runs[run_id] = "running"
        return run_id

    def get_document(self, document_id: str) -> DocumentState | None:
        return self.documents.get(document_id)

    def replace_document(
        self,
        document: ManifestDocument,
        chunks: list[Chunk],
        fingerprint: str,
        embedding_model: str,
        object_key: str,
    ) -> None:
        self.replace_calls += 1
        if self.fail_replace_once:
            self.fail_replace_once = False
            raise RuntimeError("injected registry write failure")
        self.documents[str(document.metadata["doc_id"])] = DocumentState(
            fingerprint=fingerprint,
            chunk_ids=tuple(chunk.chunk_id for chunk in chunks),
            object_key=object_key,
        )

    def finish_run(
        self,
        run_id: str,
        docs_seen: int,
        docs_changed: int,
        chunks_written: int,
    ) -> None:
        self.runs[run_id] = "succeeded"

    def fail_run(self, run_id: str, error_category: str) -> None:
        self.runs[run_id] = f"failed:{error_category}"


class FakePdfStore:
    def __init__(self) -> None:
        self.objects: set[str] = set()
        self.upload_calls = 0

    def ensure_bucket(self) -> None:
        return None

    def exists(self, object_key: str) -> bool:
        return object_key in self.objects

    def upload(self, document: ManifestDocument, object_key: str) -> None:
        self.upload_calls += 1
        self.objects.add(object_key)


class FakeVectorStore:
    def __init__(self) -> None:
        self.points: dict[str, dict[str, object]] = {}
        self.upsert_calls = 0
        self.delete_calls = 0
        self.fail_upsert_once = False

    def ensure_collection(self) -> None:
        return None

    def point_ids_match(
        self,
        point_ids: list[str],
        payloads: list[dict[str, str | int | None]],
    ) -> set[str]:
        expected_by_id = dict(zip(point_ids, payloads, strict=True))
        return {
            point_id
            for point_id in point_ids
            if point_id in self.points
            and self.points[point_id].keys() == expected_by_id[point_id].keys()
            and all(
                type(self.points[point_id][key]) is type(expected_by_id[point_id][key])
                and self.points[point_id][key] == expected_by_id[point_id][key]
                for key in expected_by_id[point_id]
            )
        }

    def document_point_ids(self, document_id: str) -> set[str]:
        return {
            point_id
            for point_id, payload in self.points.items()
            if payload.get("doc_id") == document_id
        }

    def document_point_ids(self, document_id: str) -> set[str]:
        return {
            point_id
            for point_id, payload in self.points.items()
            if payload.get("doc_id") == document_id
        }

    def upsert(
        self,
        point_ids: list[str],
        vectors: list[list[float]],
        payloads: list[dict[str, object]],
    ) -> None:
        self.upsert_calls += 1
        if self.fail_upsert_once:
            self.fail_upsert_once = False
            raise RuntimeError("injected Qdrant write failure")
        self.points.update(dict(zip(point_ids, payloads, strict=True)))

    def delete(self, point_ids: list[str]) -> None:
        self.delete_calls += 1
        for point_id in point_ids:
            self.points.pop(point_id, None)


class FakeEmbedder:
    def __init__(self) -> None:
        self.calls = 0
        self.text_count = 0

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        self.text_count += len(texts)
        return [[0.1] * 1536 for _ in texts]


@pytest.fixture
def ingestion_dependencies() -> tuple[FakeRegistry, FakePdfStore, FakeVectorStore, FakeEmbedder]:
    return FakeRegistry(), FakePdfStore(), FakeVectorStore(), FakeEmbedder()


def test_first_run_persists_all_documents_and_chunks(ingestion_dependencies: tuple) -> None:
    registry, pdf_store, vector_store, embedder = ingestion_dependencies

    summary = ingest_documents(
        load_manifest(GENERATED_DIR),
        registry=registry,
        pdf_store=pdf_store,
        vector_store=vector_store,
        embedder=embedder,
    )

    assert isinstance(summary, IngestionSummary)
    assert summary.docs_seen == 8
    assert summary.docs_changed == 8
    assert len(registry.documents) == 8
    assert len(pdf_store.objects) == 8
    assert len(vector_store.points) == summary.chunks_written
    assert embedder.text_count == summary.chunks_written
    assert list(registry.runs.values()) == ["succeeded"]


def test_unchanged_rerun_is_a_true_noop(ingestion_dependencies: tuple) -> None:
    registry, pdf_store, vector_store, embedder = ingestion_dependencies
    documents = load_manifest(GENERATED_DIR)
    ingest_documents(
        documents,
        registry=registry,
        pdf_store=pdf_store,
        vector_store=vector_store,
        embedder=embedder,
    )
    prior_calls = (embedder.calls, pdf_store.upload_calls, vector_store.upsert_calls)

    summary = ingest_documents(
        documents,
        registry=registry,
        pdf_store=pdf_store,
        vector_store=vector_store,
        embedder=embedder,
    )

    assert summary.docs_changed == 0
    assert summary.chunks_written == 0
    assert (embedder.calls, pdf_store.upload_calls, vector_store.upsert_calls) == prior_calls


def test_rerun_repairs_missing_qdrant_point(ingestion_dependencies: tuple) -> None:
    registry, pdf_store, vector_store, embedder = ingestion_dependencies
    documents = load_manifest(GENERATED_DIR)
    ingest_documents(
        documents,
        registry=registry,
        pdf_store=pdf_store,
        vector_store=vector_store,
        embedder=embedder,
    )
    point_id = next(iter(vector_store.points))
    vector_store.points.pop(point_id)
    previous_embedding_calls = embedder.calls

    summary = ingest_documents(
        documents,
        registry=registry,
        pdf_store=pdf_store,
        vector_store=vector_store,
        embedder=embedder,
    )

    assert summary.docs_changed == 1
    assert point_id in vector_store.points
    assert embedder.calls == previous_embedding_calls + 1


def test_rerun_repairs_wrong_payload_scalar_type(ingestion_dependencies: tuple) -> None:
    registry, pdf_store, vector_store, embedder = ingestion_dependencies
    document = load_manifest(GENERATED_DIR)[0]
    ingest_documents(
        [document],
        registry=registry,
        pdf_store=pdf_store,
        vector_store=vector_store,
        embedder=embedder,
    )
    point_id = next(iter(vector_store.points))
    vector_store.points[point_id]["page"] = True

    summary = ingest_documents(
        [document],
        registry=registry,
        pdf_store=pdf_store,
        vector_store=vector_store,
        embedder=embedder,
    )

    assert summary.docs_changed == 1
    assert type(vector_store.points[point_id]["page"]) is int


def test_changed_metadata_replaces_document_registry(ingestion_dependencies: tuple) -> None:
    registry, pdf_store, vector_store, embedder = ingestion_dependencies
    documents = load_manifest(GENERATED_DIR)
    ingest_documents(
        documents[:1],
        registry=registry,
        pdf_store=pdf_store,
        vector_store=vector_store,
        embedder=embedder,
    )
    changed_metadata = {**documents[0].metadata, "title": "Revised title"}
    revised_document = replace(documents[0], metadata=changed_metadata)

    summary = ingest_documents(
        [revised_document],
        registry=registry,
        pdf_store=pdf_store,
        vector_store=vector_store,
        embedder=embedder,
    )

    assert summary.docs_changed == 1
    assert registry.replace_calls == 2
    assert len(vector_store.points) == len(
        registry.documents[str(changed_metadata["doc_id"])].chunk_ids
    )


def test_changed_registry_object_key_is_reconciled(ingestion_dependencies: tuple) -> None:
    registry, pdf_store, vector_store, embedder = ingestion_dependencies
    document = load_manifest(GENERATED_DIR)[0]
    ingest_documents(
        [document],
        registry=registry,
        pdf_store=pdf_store,
        vector_store=vector_store,
        embedder=embedder,
    )
    document_id = str(document.metadata["doc_id"])
    prior_state = registry.documents[document_id]
    registry.documents[document_id] = replace(prior_state, object_key="wrong/key.pdf")
    previous_uploads = pdf_store.upload_calls

    summary = ingest_documents(
        [document],
        registry=registry,
        pdf_store=pdf_store,
        vector_store=vector_store,
        embedder=embedder,
    )

    assert summary.docs_changed == 1
    assert pdf_store.upload_calls == previous_uploads + 1
    assert registry.documents[document_id].object_key == object_key_for(document)


def test_manifest_omission_does_not_delete_stored_documents(ingestion_dependencies: tuple) -> None:
    registry, pdf_store, vector_store, embedder = ingestion_dependencies
    documents = load_manifest(GENERATED_DIR)
    ingest_documents(
        documents,
        registry=registry,
        pdf_store=pdf_store,
        vector_store=vector_store,
        embedder=embedder,
    )
    prior_ids = set(registry.documents)

    ingest_documents(
        documents[:1],
        registry=registry,
        pdf_store=pdf_store,
        vector_store=vector_store,
        embedder=embedder,
    )

    assert set(registry.documents) == prior_ids


def test_retry_converges_after_qdrant_failure(ingestion_dependencies: tuple) -> None:
    registry, pdf_store, vector_store, embedder = ingestion_dependencies
    documents = load_manifest(GENERATED_DIR)[:1]
    vector_store.fail_upsert_once = True

    with pytest.raises(RuntimeError, match="injected Qdrant write failure"):
        ingest_documents(
            documents,
            registry=registry,
            pdf_store=pdf_store,
            vector_store=vector_store,
            embedder=embedder,
        )

    assert next(iter(registry.runs.values())).startswith("failed:")
    summary = ingest_documents(
        documents,
        registry=registry,
        pdf_store=pdf_store,
        vector_store=vector_store,
        embedder=embedder,
    )

    assert summary.docs_changed == 1
    assert len(registry.documents) == 1
    assert len(vector_store.points) == summary.chunks_written


def test_retry_removes_orphan_points_after_registry_failure_and_content_shrinks(
    ingestion_dependencies: tuple,
) -> None:
    registry, pdf_store, vector_store, embedder = ingestion_dependencies
    document = load_manifest(GENERATED_DIR)[0]
    registry.fail_replace_once = True
    long_pages = [PageText(page=1, text="1.1 " + "coverage " * 900)]
    short_pages = [PageText(page=1, text="1.1 covered.")]

    with patch("rag.ingestion.pipeline.extract_pdf_pages", return_value=long_pages):
        with pytest.raises(RuntimeError, match="injected registry write failure"):
            ingest_documents(
                [document],
                registry=registry,
                pdf_store=pdf_store,
                vector_store=vector_store,
                embedder=embedder,
            )

    assert len(vector_store.points) > 1
    changed_document = replace(document, pdf_sha256="f" * 64)
    with patch("rag.ingestion.pipeline.extract_pdf_pages", return_value=short_pages):
        summary = ingest_documents(
            [changed_document],
            registry=registry,
            pdf_store=pdf_store,
            vector_store=vector_store,
            embedder=embedder,
        )

    desired_ids = set(registry.documents[str(document.metadata["doc_id"])].chunk_ids)
    assert summary.chunks_written == 1
    assert set(vector_store.points) == desired_ids
