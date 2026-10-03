import json

import httpx
import pytest

from rag.retrieval.generation import (
    GenerationError,
    LiteLLMAnswerGenerator,
)
from rag.retrieval.answer import AnswerValidationError
from rag.retrieval.models import RetrievedChunk


def retrieved_chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id="chunk-1",
        ref="C1",
        doc_id="POL-HOME-002-v2",
        title="Home Policy",
        section="4",
        clause="4.2",
        page=3,
        score=0.82,
        text="Flood damage is covered subject to the stated limits.",
    )


def test_generator_sends_refs_as_json_evidence_and_parses_valid_claims() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "abstain": False,
                                    "claims": [
                                        {"text": "Flood damage is covered.", "refs": ["C1"]}
                                    ],
                                }
                            )
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": 27,
                    "completion_tokens": 8,
                    "total_tokens": 35,
                },
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handle))
    generator = LiteLLMAnswerGenerator(
        client=client,
        base_url="http://litellm:4000",
        master_key="test-secret",
        model="gpt-oss-20b",
    )

    answer = generator.generate("Is flood damage covered?", [retrieved_chunk()])

    assert answer.answer == "Flood damage is covered. [C1]"
    assert answer.citations[0].chunk_id == "chunk-1"
    assert answer.prompt_tokens == 27
    assert answer.completion_tokens == 8
    assert answer.total_tokens == 35
    request = requests[0]
    assert request.url == "http://litellm:4000/chat/completions"
    assert request.headers["authorization"] == "Bearer test-secret"
    payload = json.loads(request.content)
    assert payload["model"] == "gpt-oss-20b"
    assert payload["max_completion_tokens"] == 800
    assert payload["response_format"] == {"type": "json_object"}
    assert "C1" in payload["messages"][1]["content"]
    assert "Flood damage is covered subject to the stated limits." in payload["messages"][1]["content"]
    client.close()


def test_generator_sanitizes_upstream_errors() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(429, text="upstream secret detail")
        )
    )
    generator = LiteLLMAnswerGenerator(
        client=client,
        base_url="http://litellm:4000",
        master_key="test-secret",
        model="gpt-oss-20b",
    )

    with pytest.raises(GenerationError, match="HTTP 429") as error:
        generator.generate("Question?", [retrieved_chunk()])

    assert "upstream secret detail" not in str(error.value)
    assert "test-secret" not in str(error.value)
    client.close()


def test_generator_rejects_non_object_message_as_invalid_evidence() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"choices": [{"message": []}]},
            )
        )
    )
    generator = LiteLLMAnswerGenerator(
        client=client,
        base_url="http://litellm:4000",
        master_key="test-secret",
        model="gpt-oss-20b",
    )

    with pytest.raises(AnswerValidationError, match="invalid grounded answer"):
        generator.generate("Question?", [retrieved_chunk()])
    client.close()