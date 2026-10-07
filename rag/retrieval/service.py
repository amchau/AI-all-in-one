from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from dataclasses import replace
from math import isfinite
import time
from typing import Any, Protocol

from opentelemetry import trace
from opentelemetry.trace import Span, Status, StatusCode

from rag.ingestion.embed import EmbeddingError
from rag.retrieval.answer import AnswerValidationError
from rag.retrieval.models import (
    GroundedAnswer,
    GroundedInvestigation,
    RagQueryInput,
    RagQueryResult,
    RetrievedChunk,
    SourceDocument,
)
from rag.retrieval.rerank import Reranker
from rag.retrieval.search import candidate_pool_size, search_dense, search_hybrid
from rag.retrieval.sources import select_eligible_sources


tracer = trace.get_tracer(__name__)


@contextmanager
def _start_rag_span(name: str) -> Iterator[Span]:
    with tracer.start_as_current_span(
        name,
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            yield span
        except Exception:
            span.set_status(Status(StatusCode.ERROR))
            raise


def _record_score_range(span: Any, chunks: list[RetrievedChunk]) -> None:
    if not chunks:
        return
    scores = [chunk.score for chunk in chunks]
    span.set_attribute("rag.score_min", min(scores))
    span.set_attribute("rag.score_max", max(scores))


class SourceRepository(Protocol):
    def list_for_policy(self, policy_id: str) -> list[SourceDocument]: ...


class TextEmbedder(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...


class SparseQueryEmbedder(Protocol):
    model_name: str

    def embed_query(self, text: str) -> Any: ...


class AnswerGenerator(Protocol):
    model: str

    def generate(self, question: str, chunks: list[RetrievedChunk]) -> GroundedAnswer: ...

    def generate_investigation(
        self,
        question: str,
        chunks: list[RetrievedChunk],
    ) -> GroundedInvestigation: ...


class QueryDependencyError(RuntimeError):
    """Raised when a query dependency fails or returns invalid data."""


class RagQueryService:
    def __init__(
        self,
        *,
        source_repository: SourceRepository,
        embedder: TextEmbedder,
        sparse_embedder: SparseQueryEmbedder | None = None,
        qdrant_client: Any,
        reranker: Reranker | None = None,
        answer_generator: AnswerGenerator,
    ) -> None:
        self._source_repository = source_repository
        self._embedder = embedder
        self._sparse_embedder = sparse_embedder
        self._qdrant_client = qdrant_client
        self._reranker = reranker
        self._answer_generator = answer_generator

    def query(
        self,
        request: RagQueryInput,
        *,
        structured_investigation: bool = False,
        retrieval_only: bool = False,
    ) -> RagQueryResult:
        started_at = time.perf_counter()
        guidance_as_of = request.guidance_as_of or request.loss_date
        try:
            with _start_rag_span("rag.source_resolution") as span:
                source_documents = self._source_repository.list_for_policy(request.policy_id)
                eligible_documents = select_eligible_sources(
                    source_documents,
                    policy_id=request.policy_id,
                    loss_date=request.loss_date,
                    guidance_as_of=guidance_as_of,
                )
                span.set_attribute("rag.source_count", len(eligible_documents))
        except ValueError:
            raise
        except Exception:
            raise QueryDependencyError("source registry query failed") from None

        try:
            with _start_rag_span("rag.embed") as span:
                vectors = self._embedder.embed_texts([request.question])
                if len(vectors) != 1 or len(vectors[0]) != 1536 or any(
                    not isfinite(value) for value in vectors[0]
                ):
                    raise EmbeddingError("query embedding has invalid dimensions or values")
                query_vector = vectors[0]
                span.set_attribute("rag.embedding_model", "embed-small")
                span.set_attribute("rag.embedding_dimensions", len(query_vector))
        except Exception:
            raise QueryDependencyError("query embedding failed") from None

        candidate_count = request.top_k
        if request.mode == "dense":
            try:
                with _start_rag_span("rag.search") as span:
                    chunks = search_dense(
                        self._qdrant_client,
                        query_vector,
                        eligible_documents,
                        top_k=request.top_k,
                    )
                    span.set_attribute("rag.mode", request.mode)
                    span.set_attribute("rag.top_k", request.top_k)
                    span.set_attribute("rag.result_count", len(chunks))
                    span.set_attribute(
                        "rag.candidate_doc_ids",
                        [chunk.doc_id for chunk in chunks],
                    )
                    _record_score_range(span, chunks)
            except Exception:
                raise QueryDependencyError("dense search failed") from None
        else:
            if self._sparse_embedder is None:
                raise QueryDependencyError("sparse query encoder is unavailable")
            try:
                with _start_rag_span("rag.sparse_embed") as span:
                    sparse_query = self._sparse_embedder.embed_query(request.question)
                    span.set_attribute("rag.sparse_model", self._sparse_embedder.model_name)
                    span.set_attribute("rag.sparse_vector_size", len(sparse_query.indices))
            except Exception:
                raise QueryDependencyError("sparse query encoding failed") from None
            candidate_count = candidate_pool_size(request.top_k)
            try:
                with _start_rag_span("rag.search") as span:
                    chunks = search_hybrid(
                        self._qdrant_client,
                        query_vector,
                        sparse_query,
                        eligible_documents,
                        limit=candidate_count,
                    )
                    span.set_attribute("rag.mode", request.mode)
                    span.set_attribute("rag.top_k", request.top_k)
                    span.set_attribute("rag.candidate_count", candidate_count)
                    span.set_attribute("rag.result_count", len(chunks))
                    span.set_attribute(
                        "rag.candidate_doc_ids",
                        [chunk.doc_id for chunk in chunks],
                    )
                    _record_score_range(span, chunks)
            except Exception:
                raise QueryDependencyError("hybrid search failed") from None
            if request.mode == "hybrid_rerank":
                if self._reranker is None:
                    raise QueryDependencyError("reranker is unavailable")
                try:
                    with _start_rag_span("rag.rerank") as span:
                        chunks = self._reranker.rerank(request.question, chunks)
                        span.set_attribute("rag.reranker_model", self._reranker.model_name)
                        span.set_attribute("rag.candidate_count", candidate_count)
                        span.set_attribute("rag.result_count", len(chunks))
                        span.set_attribute(
                            "rag.reranked_doc_ids",
                            [chunk.doc_id for chunk in chunks],
                        )
                        span.set_attribute(
                            "rag.returned_doc_ids",
                            [chunk.doc_id for chunk in chunks[: request.top_k]],
                        )
                        _record_score_range(span, chunks)
                except Exception:
                    raise QueryDependencyError("reranking failed") from None
            chunks = chunks[: request.top_k]
        if request.mode != "dense":
            chunks = [
                replace(chunk, ref=f"C{index}")
                for index, chunk in enumerate(chunks, start=1)
            ]

        answer = GroundedAnswer(
            status="insufficient_evidence",
            answer="",
            citations=[],
        )
        investigation: GroundedInvestigation | None = (
            GroundedInvestigation(
                status="insufficient_evidence",
                summary="",
                summary_refs=(),
                findings=(),
                unresolved_questions=(),
                citations=[],
            )
            if structured_investigation
            else None
        )
        if chunks and not retrieval_only:
            try:
                with _start_rag_span("rag.generate") as span:
                    if structured_investigation:
                        investigation = self._answer_generator.generate_investigation(
                            request.question,
                            chunks,
                        )
                        rendered_claims = [
                            f"{investigation.summary} "
                            + ", ".join(f"[{ref}]" for ref in investigation.summary_refs)
                        ]
                        rendered_claims.extend(
                            f"{finding.text} "
                            + ", ".join(f"[{ref}]" for ref in finding.refs)
                            for finding in investigation.findings
                        )
                        answer = GroundedAnswer(
                            status=investigation.status,
                            answer="\n".join(rendered_claims),
                            citations=investigation.citations,
                            prompt_tokens=investigation.prompt_tokens,
                            completion_tokens=investigation.completion_tokens,
                            total_tokens=investigation.total_tokens,
                        )
                    else:
                        answer = self._answer_generator.generate(request.question, chunks)
                    span.set_attribute("rag.model", self._answer_generator.model)
                    span.set_attribute("rag.citation_count", len(answer.citations))
                    for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
                        count = getattr(answer, name)
                        if count is not None:
                            span.set_attribute(f"llm.{name}", count)
            except AnswerValidationError:
                answer = GroundedAnswer(
                    status="insufficient_evidence",
                    answer="",
                    citations=[],
                )
                if structured_investigation:
                    investigation = GroundedInvestigation(
                        status="insufficient_evidence",
                        summary="",
                        summary_refs=(),
                        findings=(),
                        unresolved_questions=(),
                        citations=[],
                    )
            except Exception:
                raise QueryDependencyError("grounded generation failed") from None

        return RagQueryResult(
            answer=answer,
            chunks=chunks,
            model=self._answer_generator.model,
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            mode=request.mode,
            investigation=investigation,
        )