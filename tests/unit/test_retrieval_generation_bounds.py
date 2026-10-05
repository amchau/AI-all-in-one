import json

import httpx
import pytest

from rag.retrieval.generation import GenerationError, LiteLLMAnswerGenerator
from rag.retrieval.models import RetrievedChunk


def chunks(count: int) -> list[RetrievedChunk]:
    return [
        RetrievedChunk(
            chunk_id=f"chunk-{index}",
            ref=f"C{index}",
            doc_id="POL-HOME-002-v2",
            title="Home Policy",
            section="4",
            clause=f"4.{index}",
            page=index,
            score=1.0 - index / 100,
            text=f"Synthetic evidence clause {index}.",
        )
        for index in range(1, count + 1)
    ]


def success_response() -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "abstain": False,
                            "claims": [
                                {"text": "Evidence supports this statement.", "refs": ["C1"]}
                            ],
                        }
                    )
                }
            }
        ],
        "usage": {"prompt_tokens": 40, "completion_tokens": 12},
    }


def generator(client: httpx.Client) -> LiteLLMAnswerGenerator:
    return LiteLLMAnswerGenerator(
        client=client,
        base_url="http://litellm:4000",
        master_key="test-secret",
        model="gpt-oss-20b",
    )


def test_generation_bounds_context_and_retries_only_allowlisted_json_error() -> None:
    requests: list[dict[str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            return httpx.Response(
                400,
                json={"error": {"code": "json_validate_failed", "message": "redacted"}},
            )
        return httpx.Response(200, json=success_response())

    client = httpx.Client(transport=httpx.MockTransport(handle))
    result = generator(client).generate("Question?", chunks(20))

    assert len(requests) == 2
    evidence_counts = [
        len(json.loads(body["messages"][1]["content"])["evidence"])
        for body in requests
    ]
    assert evidence_counts == [8, 4]
    assert [item.ref for item in result.citations] == ["C1"]
    assert result.citations[0].chunk_id == "chunk-1"
    client.close()


def test_generation_does_not_retry_other_upstream_errors() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            429,
            json={"error": {"code": "rate_limit_exceeded", "message": "private"}},
        )

    client = httpx.Client(transport=httpx.MockTransport(handle))
    with pytest.raises(GenerationError, match="HTTP 429"):
        generator(client).generate("Question?", chunks(20))

    assert len(requests) == 1
    client.close()


def test_generation_retry_failure_is_not_repeated() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            400,
            json={"error": {"code": "json_validate_failed", "message": "private"}},
        )

    client = httpx.Client(transport=httpx.MockTransport(handle))
    with pytest.raises(GenerationError, match="HTTP 400"):
        generator(client).generate("Question?", chunks(20))

    assert len(requests) == 2
    assert len(json.loads(requests[1].content)["messages"][1]["content"]) < len(
        json.loads(requests[0].content)["messages"][1]["content"]
    )
    client.close()


def test_generation_does_not_retry_successful_malformed_json() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "not-json"}}]},
        )

    client = httpx.Client(transport=httpx.MockTransport(handle))
    with pytest.raises(Exception, match="invalid grounded answer"):
        generator(client).generate("Question?", chunks(20))

    assert len(requests) == 1
    client.close()
