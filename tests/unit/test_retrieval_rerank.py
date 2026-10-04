import httpx
import pytest

from rag.retrieval.models import RetrievedChunk
from rag.retrieval.rerank import RerankingError, TeiReranker


def chunks() -> list[RetrievedChunk]:
    return [
        RetrievedChunk(
            chunk_id="chunk-1",
            ref="C1",
            doc_id="POL-HOME-002-v2",
            title="Home Policy",
            section="4",
            clause="4.1",
            page=3,
            score=0.04,
            text="Flood exclusion wording.",
            hybrid_score=0.04,
        ),
        RetrievedChunk(
            chunk_id="chunk-2",
            ref="C2",
            doc_id="POL-HOME-002-v2",
            title="Home Policy",
            section="4",
            clause="4.2",
            page=4,
            score=0.03,
            text="Flood extension wording.",
            hybrid_score=0.03,
        ),
    ]


def test_tei_reranker_sorts_by_score_and_preserves_hybrid_score() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json=[{"index": 0, "score": 0.2}, {"index": 1, "score": 0.9}],
        )

    client = httpx.Client(transport=httpx.MockTransport(handle))
    reranker = TeiReranker(client=client, base_url="http://reranker:8080")

    results = reranker.rerank("Is flood damage covered?", chunks())

    assert [chunk.chunk_id for chunk in results] == ["chunk-2", "chunk-1"]
    assert results[0].hybrid_score == 0.03
    assert results[0].rerank_score == 0.9
    assert results[0].score == 0.9
    assert requests[0].url == "http://reranker:8080/rerank"
    assert requests[0].read().decode().find("Is flood damage covered?") >= 0
    client.close()


@pytest.mark.parametrize(
    "payload",
    [
        [{"index": 0, "score": 0.2}],
        [{"index": 0, "score": 0.2}, {"index": 0, "score": 0.9}],
        [{"index": 0, "score": "not-a-number"}, {"index": 1, "score": 0.9}],
        [{"index": 0, "score": 0.2}, {"index": 3, "score": 0.9}],
    ],
)
def test_tei_reranker_rejects_invalid_rankings(payload: object) -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    )
    reranker = TeiReranker(client=client, base_url="http://reranker:8080")

    with pytest.raises(RerankingError, match="invalid ranking"):
        reranker.rerank("Is flood damage covered?", chunks())
    client.close()


def test_tei_reranker_sanitizes_http_failures() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(503, text="private upstream detail")
        )
    )
    reranker = TeiReranker(client=client, base_url="http://reranker:8080")

    with pytest.raises(RerankingError, match="HTTP 503") as error:
        reranker.rerank("Is flood damage covered?", chunks())

    assert "private upstream detail" not in str(error.value)
    client.close()