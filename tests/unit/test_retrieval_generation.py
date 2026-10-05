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


def test_generator_returns_structured_grounded_investigation() -> None:
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
                                    "summary": {
                                        "text": "Flood cover is subject to limits.",
                                        "refs": ["C1"],
                                    },
                                    "findings": [
                                        {
                                            "text": "The policy limits flood cover.",
                                            "refs": ["C1"],
                                        }
                                    ],
                                    "unresolved_questions": [
                                        "What is the estimated repair cost?"
                                    ],
                                }
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 50, "completion_tokens": 20},
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handle))
    generator = LiteLLMAnswerGenerator(
        client=client,
        base_url="http://litellm:4000",
        master_key="test-secret",
        model="gpt-oss-20b",
    )

    answer = generator.generate_investigation(
        "Investigate this claim narrative.", [retrieved_chunk()]
    )

    assert answer.summary == "Flood cover is subject to limits."
    assert answer.findings[0].refs == ("C1",)
    assert answer.unresolved_questions == ("What is the estimated repair cost?",)
    assert answer.prompt_tokens == 50
    assert answer.completion_tokens == 20
    payload = json.loads(requests[0].content)
    assert "response_format" not in payload
    assert payload["max_completion_tokens"] == 1200
    assert "Do not apply policy terms to decide this claim." in payload["messages"][0]["content"]
    assert '"findings":[{"text":"...","refs":["C1"]}]' in payload["messages"][0]["content"]
    client.close()


def test_investigation_generator_reports_provider_refusal_as_generation_error() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"refusal": "I cannot answer that request."}}
                    ]
                },
            )
        )
    )
    generator = LiteLLMAnswerGenerator(
        client=client,
        base_url="http://litellm:4000",
        master_key="test-secret",
        model="gpt-oss-20b",
    )

    with pytest.raises(GenerationError, match="refused structured investigation"):
        generator.generate_investigation(
            "Investigate the reported loss.", [retrieved_chunk()]
        )
    client.close()


def test_investigation_generator_reports_content_filter_as_generation_error() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "content_filter",
                            "message": {"content": None},
                        }
                    ]
                },
            )
        )
    )
    generator = LiteLLMAnswerGenerator(
        client=client,
        base_url="http://litellm:4000",
        master_key="test-secret",
        model="gpt-oss-20b",
    )

    with pytest.raises(GenerationError, match="content filter"):
        generator.generate_investigation(
            "Investigate the reported loss.", [retrieved_chunk()]
        )
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