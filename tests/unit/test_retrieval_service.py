from datetime import date
from dataclasses import replace
from types import SimpleNamespace

import pytest

from rag.retrieval.answer import AnswerValidationError
from rag.retrieval.models import GroundedAnswer, SourceDocument
from rag.ingestion.sparse import SparseVectorData
from rag.retrieval.service import (
    QueryDependencyError,
    RagQueryInput,
    RagQueryService,
)


class FakeRepository:
    def __init__(self, documents: list[SourceDocument]) -> None:
        self.documents = documents

    def list_for_policy(self, policy_id: str) -> list[SourceDocument]:
        return self.documents


class FakeEmbedder:
    def __init__(self) -> None:
        self.inputs: list[str] = []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.inputs.extend(texts)
        return [[0.1] * 1536]


class FakeSparseEmbedder:
    model_name = "Qdrant/bm25"

    def __init__(self) -> None:
        self.inputs: list[str] = []

    def embed_query(self, text: str) -> SparseVectorData:
        self.inputs.append(text)
        return SparseVectorData(indices=[3, 8], values=[1.0, 1.0])


class FakeReranker:
    model_name = "BAAI/bge-reranker-base"

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[tuple[str, list[object]]] = []
        self.fail = fail

    def rerank(self, query: str, chunks: list[object]) -> list[object]:
        self.calls.append((query, chunks))
        if self.fail:
            raise RuntimeError("private TEI detail")
        return [
            replace(
                chunk,
                score=0.9,
                rerank_score=0.9,
                hybrid_score=chunk.hybrid_score,
            )
            for chunk in reversed(chunks)
        ]


class FakeGenerator:
    model = "gpt-oss-20b"

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[object]]] = []

    def generate(self, question: str, chunks: list[object]) -> GroundedAnswer:
        self.calls.append((question, chunks))
        chunk = chunks[0]
        return GroundedAnswer(
            status="answered",
            answer=f"Covered. [{chunk.ref}]",
            citations=[chunk.citation()],
        )


class FakeQdrant:
    def __init__(self, points: list[SimpleNamespace] | None = None) -> None:
        self.query: dict[str, object] | None = None
        self.points = points or [
            SimpleNamespace(
                id="chunk-1",
                score=0.82,
                payload={
                    "doc_id": "POL-HOME-002-v2",
                    "section": "4",
                    "clause": "4.2",
                    "page": 3,
                    "text": "Flood damage is covered subject to limits.",
                },
            )
        ]

    def query_points(self, **kwargs: object) -> SimpleNamespace:
        self.query = kwargs
        return SimpleNamespace(points=self.points)


def document() -> SourceDocument:
    return SourceDocument(
        doc_id="POL-HOME-002-v2",
        title="Home Policy",
        doc_type="policy",
        policy_id="HOME-002",
        product="home",
        effective_date=date(2025, 1, 1),
        version="2.0",
        acl="internal",
    )


def test_no_hits_return_insufficient_evidence_without_calling_generator() -> None:
    generator = FakeGenerator()
    qdrant = SimpleNamespace(query_points=lambda **kwargs: SimpleNamespace(points=[]))
    service = RagQueryService(
        source_repository=FakeRepository([document()]),
        embedder=FakeEmbedder(),
        qdrant_client=qdrant,
        answer_generator=generator,
    )

    result = service.query(
        RagQueryInput(
            question="Is flood damage covered?",
            policy_id="HOME-002",
            loss_date=date(2025, 3, 1),
            guidance_as_of=date(2026, 1, 1),
            top_k=5,
        )
    )

    assert result.answer.status == "insufficient_evidence"
    assert result.answer.answer == ""
    assert result.chunks == []
    assert generator.calls == []


def test_success_embeds_question_searches_dense_and_generates_grounded_answer() -> None:
    embedder = FakeEmbedder()
    qdrant = FakeQdrant()
    generator = FakeGenerator()
    service = RagQueryService(
        source_repository=FakeRepository([document()]),
        embedder=embedder,
        qdrant_client=qdrant,
        answer_generator=generator,
    )

    result = service.query(
        RagQueryInput(
            question="Is flood damage covered?",
            policy_id="HOME-002",
            loss_date=date(2025, 3, 1),
        )
    )

    assert embedder.inputs == ["Is flood damage covered?"]
    assert qdrant.query is not None
    assert qdrant.query["using"] == "dense"
    assert result.answer.status == "answered"
    assert result.answer.answer.endswith("[C1]")
    assert result.answer.citations[0].chunk_id == "chunk-1"
    assert result.mode == "dense"
    assert result.chunks[0].dense_score == 0.82


def test_hybrid_uses_sparse_rrf_but_does_not_call_reranker() -> None:
    sparse_embedder = FakeSparseEmbedder()
    reranker = FakeReranker()
    qdrant = FakeQdrant()
    service = RagQueryService(
        source_repository=FakeRepository([document()]),
        embedder=FakeEmbedder(),
        sparse_embedder=sparse_embedder,
        qdrant_client=qdrant,
        reranker=reranker,
        answer_generator=FakeGenerator(),
    )

    result = service.query(
        RagQueryInput(
            question="Is flood damage covered?",
            policy_id="HOME-002",
            loss_date=date(2025, 3, 1),
            mode="hybrid",
            top_k=2,
        )
    )

    assert sparse_embedder.inputs == ["Is flood damage covered?"]
    assert qdrant.query is not None
    assert qdrant.query["limit"] == 20
    assert len(qdrant.query["prefetch"]) == 2
    assert reranker.calls == []
    assert result.mode == "hybrid"
    assert result.chunks[0].hybrid_score == result.chunks[0].score


def test_hybrid_rerank_reorders_candidates_before_citations_and_limits_output() -> None:
    qdrant = FakeQdrant(
        [
            SimpleNamespace(
                id=f"chunk-{index}",
                score=0.04 - index / 100,
                payload={
                    "doc_id": "POL-HOME-002-v2",
                    "section": "4",
                    "clause": f"4.{index}",
                    "page": index + 1,
                    "text": f"Flood wording {index}.",
                },
            )
            for index in range(1, 4)
        ]
    )
    reranker = FakeReranker()
    generator = FakeGenerator()
    service = RagQueryService(
        source_repository=FakeRepository([document()]),
        embedder=FakeEmbedder(),
        sparse_embedder=FakeSparseEmbedder(),
        qdrant_client=qdrant,
        reranker=reranker,
        answer_generator=generator,
    )

    result = service.query(
        RagQueryInput(
            question="Is flood damage covered?",
            policy_id="HOME-002",
            loss_date=date(2025, 3, 1),
            mode="hybrid_rerank",
            top_k=1,
        )
    )

    assert qdrant.query is not None
    assert qdrant.query["limit"] == 20
    assert len(reranker.calls[0][1]) == 3
    assert len(result.chunks) == 1
    assert result.chunks[0].chunk_id == "chunk-3"
    assert result.chunks[0].ref == "C1"
    assert result.chunks[0].score == result.chunks[0].rerank_score == 0.9
    assert result.chunks[0].hybrid_score is not None
    assert generator.calls[0][1][0].ref == "C1"
    assert result.mode == "hybrid_rerank"


def test_hybrid_reranker_failure_becomes_dependency_error_without_fallback() -> None:
    qdrant = FakeQdrant()
    reranker = FakeReranker(fail=True)
    service = RagQueryService(
        source_repository=FakeRepository([document()]),
        embedder=FakeEmbedder(),
        sparse_embedder=FakeSparseEmbedder(),
        qdrant_client=qdrant,
        reranker=reranker,
        answer_generator=FakeGenerator(),
    )

    with pytest.raises(QueryDependencyError, match="reranking failed") as error:
        service.query(
            RagQueryInput(
                question="Is flood damage covered?",
                policy_id="HOME-002",
                loss_date=date(2025, 3, 1),
                mode="hybrid_rerank",
            )
        )

    assert "private TEI detail" not in str(error.value)
    assert qdrant.query is not None


def test_invalid_generated_citations_become_insufficient_evidence() -> None:
    class InvalidGenerator(FakeGenerator):
        def generate(self, question: str, chunks: list[object]) -> GroundedAnswer:
            raise AnswerValidationError("invalid grounded answer")

    service = RagQueryService(
        source_repository=FakeRepository([document()]),
        embedder=FakeEmbedder(),
        qdrant_client=FakeQdrant(),
        answer_generator=InvalidGenerator(),
    )

    result = service.query(
        RagQueryInput(
            question="Is flood damage covered?",
            policy_id="HOME-002",
            loss_date=date(2025, 3, 1),
        )
    )

    assert result.answer.status == "insufficient_evidence"
    assert result.answer.answer == ""
    assert result.answer.citations == []


def test_query_dependency_failures_are_sanitized() -> None:
    class FailedRepository:
        def list_for_policy(self, policy_id: str) -> list[SourceDocument]:
            raise RuntimeError("private connection detail")

    service = RagQueryService(
        source_repository=FailedRepository(),
        embedder=FakeEmbedder(),
        qdrant_client=FakeQdrant(),
        answer_generator=FakeGenerator(),
    )

    with pytest.raises(QueryDependencyError, match="source registry query failed") as error:
        service.query(
            RagQueryInput(
                question="Is flood damage covered?",
                policy_id="HOME-002",
                loss_date=date(2025, 3, 1),
            )
        )
    assert "private connection detail" not in str(error.value)