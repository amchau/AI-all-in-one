from datetime import date
from types import SimpleNamespace

from rag.retrieval.models import SourceDocument
from rag.retrieval.search import search_dense


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