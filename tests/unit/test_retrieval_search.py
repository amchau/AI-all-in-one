from datetime import date
from types import SimpleNamespace

import pytest

from rag.retrieval.models import SourceDocument
from rag.retrieval.search import candidate_pool_size, search_dense, search_hybrid
from rag.ingestion.sparse import SparseVectorData


class RecordingQdrant:
    def __init__(self, points: list[SimpleNamespace]) -> None:
        self.points = points
        self.query: dict[str, object] | None = None

    def query_points(self, **kwargs: object) -> SimpleNamespace:
        self.query = kwargs
        return SimpleNamespace(points=self.points)


def test_search_uses_dense_vector_and_eligible_document_filter() -> None:
    client = RecordingQdrant(
        [
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
    )
    eligible = [
        SourceDocument(
            doc_id="POL-HOME-002-v2",
            doc_type="policy",
            policy_id="HOME-002",
            product="home",
            effective_date=date(2025, 1, 1),
            version="2.0",
            acl="internal",
            title="Home Policy",
        )
    ]

    results = search_dense(
        client,
        [0.1, 0.2],
        eligible,
        top_k=5,
    )

    assert len(results) == 1
    assert results[0].ref == "C1"
    assert results[0].title == "Home Policy"
    assert results[0].score == 0.82
    assert client.query is not None
    assert client.query["using"] == "dense"
    assert client.query["limit"] == 5
    assert client.query["with_payload"] is True
    filter_condition = client.query["query_filter"].must[0]
    assert filter_condition.key == "doc_id"
    assert filter_condition.match.any == ["POL-HOME-002-v2"]


def test_search_skips_qdrant_when_no_sources_are_eligible() -> None:
    client = RecordingQdrant([])

    results = search_dense(client, [0.1, 0.2], [], top_k=5)

    assert results == []
    assert client.query is None


def test_search_drops_payloads_without_citation_metadata() -> None:
    client = RecordingQdrant(
        [
            SimpleNamespace(
                id="chunk-bad",
                score=0.82,
                payload={"doc_id": "POL-HOME-002-v2", "text": "No page metadata"},
            )
        ]
    )
    eligible = [
        SourceDocument(
            doc_id="POL-HOME-002-v2",
            doc_type="policy",
            policy_id="HOME-002",
            product="home",
            effective_date=date(2025, 1, 1),
            version="2.0",
            acl="internal",
            title="Home Policy",
        )
    ]

    assert search_dense(client, [0.1, 0.2], eligible, top_k=5) == []


def test_search_drops_unhashable_document_ids() -> None:
    client = RecordingQdrant(
        [
            SimpleNamespace(
                id="chunk-bad",
                score=0.82,
                payload={"doc_id": ["POL-HOME-002-v2"], "text": "Invalid ID"},
            )
        ]
    )
    eligible = [
        SourceDocument(
            doc_id="POL-HOME-002-v2",
            title="Home Policy",
            doc_type="policy",
            policy_id="HOME-002",
            product="home",
            effective_date=date(2025, 1, 1),
            version="2.0",
            acl="internal",
        )
    ]

    assert search_dense(client, [0.1, 0.2], eligible, top_k=5) == []


def test_search_drops_non_object_payloads() -> None:
    client = RecordingQdrant(
        [SimpleNamespace(id="chunk-bad", score=0.82, payload=["not", "an", "object"])]
    )
    eligible = [
        SourceDocument(
            doc_id="POL-HOME-002-v2",
            title="Home Policy",
            doc_type="policy",
            policy_id="HOME-002",
            product="home",
            effective_date=date(2025, 1, 1),
            version="2.0",
            acl="internal",
        )
    ]

    assert search_dense(client, [0.1, 0.2], eligible, top_k=5) == []


def test_hybrid_search_uses_filtered_dense_sparse_prefetch_and_rrf() -> None:
    from qdrant_client import models

    client = RecordingQdrant(
        [
            SimpleNamespace(
                id="chunk-1",
                score=0.04,
                payload={
                    "doc_id": "POL-HOME-002-v2",
                    "section": "4",
                    "clause": "4.2",
                    "page": 3,
                    "text": "Flood damage is covered subject to limits.",
                },
            )
        ]
    )
    eligible = [
        SourceDocument(
            doc_id="POL-HOME-002-v2",
            title="Home Policy",
            doc_type="policy",
            policy_id="HOME-002",
            product="home",
            effective_date=date(2025, 1, 1),
            version="2.0",
            acl="internal",
        )
    ]

    results = search_hybrid(
        client,
        [0.1, 0.2],
        SparseVectorData(indices=[2, 8], values=[1.0, 1.0]),
        eligible,
        limit=20,
    )

    assert len(results) == 1
    assert results[0].score == 0.04
    assert results[0].hybrid_score == 0.04
    assert results[0].dense_score is None
    assert client.query is not None
    prefetches = client.query["prefetch"]
    assert len(prefetches) == 2
    assert [item.using for item in prefetches] == ["dense", "sparse"]
    assert [item.limit for item in prefetches] == [20, 20]
    assert all(item.filter.must[0].match.any == ["POL-HOME-002-v2"] for item in prefetches)
    assert isinstance(prefetches[1].query, models.SparseVector)
    assert client.query["query"].fusion == models.Fusion.RRF
    assert client.query["limit"] == 20


@pytest.mark.parametrize("top_k,expected", [(1, 20), (5, 20), (6, 24), (20, 50)])
def test_candidate_pool_size_is_bounded(top_k: int, expected: int) -> None:
    assert candidate_pool_size(top_k) == expected


@pytest.mark.parametrize("top_k", [0, 21])
def test_candidate_pool_size_rejects_out_of_range_top_k(top_k: int) -> None:
    with pytest.raises(ValueError, match="top_k"):
        candidate_pool_size(top_k)