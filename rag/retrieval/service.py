from __future__ import annotations

from datetime import date
from dataclasses import replace
from math import isfinite
import time
from typing import Any, Protocol

from opentelemetry import trace

from rag.ingestion.embed import EmbeddingError
from rag.retrieval.answer import AnswerValidationError
from rag.retrieval.models import (
    GroundedAnswer,
    RagQueryInput,
    RagQueryResult,
    RetrievedChunk,
    SourceDocument,
)
from rag.retrieval.rerank import Reranker
from rag.retrieval.search import candidate_pool_size, search_dense, search_hybrid
from rag.retrieval.sources import select_eligible_sources


tracer = trace.get_tracer(__name__)


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

    def query(self, request: RagQueryInput) -> RagQueryResult:
        started_at = time.perf_counter()
        guidance_as_of = request.guidance_as_of or request.loss_date
        try:
            with tracer.start_as_current_span("rag.source_resolution") as span:
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
        except Exception as error:
            raise QueryDependencyError("source registry query failed") from error

        try:
            with tracer.start_as_current_span("rag.embed") as span:
                vectors = self._embedder.embed_texts([request.question])
                if len(vectors) != 1 or len(vectors[0]) != 1536 or any(
                    not isfinite(value) for value in vectors[0]
                ):
                    raise EmbeddingError("query embedding has invalid dimensions or values")
                query_vector = vectors[0]
                span.set_attribute("rag.embedding_model", "embed-small")
                span.set_attribute("rag.embedding_dimensions", len(query_vector))
        except Exception as error:
            raise QueryDependencyError("query embedding failed") from error

        candidate_count = request.top_k
        if request.mode == "dense":
            try:
                with tracer.start_as_current_span("rag.search") as span:
                    chunks = search_dense(
                        self._qdrant_client,
                        query_vector,
                        eligible_documents,
                        top_k=request.top_k,
                    )
                    span.set_attribute("rag.mode", request.mode)
                    span.set_attribute("rag.top_k", request.top_k)
                    span.set_attribute("rag.result_count", len(chunks))
                    _record_score_range(span, chunks)
            except Exception as error:
                raise QueryDependencyError("dense search failed") from error
        else:
            if self._sparse_embedder is None:
                raise QueryDependencyError("sparse query encoder is unavailable")
            try:
                with tracer.start_as_current_span("rag.sparse_embed") as span:
                    sparse_query = self._sparse_embedder.embed_query(request.question)
                    span.set_attribute("rag.sparse_model", self._sparse_embedder.model_name)
                    span.set_attribute("rag.sparse_vector_size", len(sparse_query.indices))
            except Exception as error:
                raise QueryDependencyError("sparse query encoding failed") from error
            candidate_count = candidate_pool_size(request.top_k)
            try:
                with tracer.start_as_current_span("rag.search") as span:
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
                    _record_score_range(span, chunks)
            except Exception as error:
                raise QueryDependencyError("hybrid search failed") from error
            if request.mode == "hybrid_rerank":
                if self._reranker is None:
                    raise QueryDependencyError("reranker is unavailable")
                try:
                    with tracer.start_as_current_span("rag.rerank") as span:
                        chunks = self._reranker.rerank(request.question, chunks)
                        span.set_attribute("rag.reranker_model", self._reranker.model_name)
                        span.set_attribute("rag.candidate_count", candidate_count)
                        span.set_attribute("rag.result_count", len(chunks))
                        _record_score_range(span, chunks)
                except Exception as error:
                    raise QueryDependencyError("reranking failed") from error
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
        if chunks:
            try:
                with tracer.start_as_current_span("rag.generate") as span:
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
            except Exception as error:
                raise QueryDependencyError("grounded generation failed") from error

        return RagQueryResult(
            answer=answer,
            chunks=chunks,
            model=self._answer_generator.model,
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            mode=request.mode,
        )