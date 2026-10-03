import pytest

from rag.retrieval.answer import (
    AnswerValidationError,
    parse_grounded_answer,
)
from rag.retrieval.models import RetrievedChunk


def chunk(chunk_id: str, ref: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        ref=ref,
        doc_id="POL-HOME-002-v2",
        title="Home Policy",
        section="4",
        clause="4.2",
        page=3,
        score=0.82,
        text="Flood damage is covered subject to the stated limits.",
    )


def test_validates_claim_refs_and_renders_inline_citations() -> None:
    result = parse_grounded_answer(
        {
            "abstain": False,
            "claims": [
                {"text": "Flood damage is covered subject to limits.", "refs": ["C1"]}
            ],
        },
        [chunk("chunk-1", "C1")],
    )

    assert result.status == "answered"
    assert result.answer == "Flood damage is covered subject to limits. [C1]"
    assert result.citations == [chunk("chunk-1", "C1").citation()]


def test_explicit_model_abstention_returns_no_answer_or_citations() -> None:
    result = parse_grounded_answer(
        {"abstain": True, "claims": []},
        [chunk("chunk-1", "C1")],
    )

    assert result.status == "insufficient_evidence"
    assert result.answer == ""
    assert result.citations == []


@pytest.mark.parametrize(
    "claims",
    [
        [{"text": "Uncited claim.", "refs": []}],
        [{"text": "Unsupported claim.", "refs": ["C9"]}],
        [{"text": "First claim.", "refs": ["C1"]}, {"text": "Missing refs", "refs": []}],
    ],
)
def test_invalid_or_missing_refs_reject_the_whole_answer(claims: list[dict[str, object]]) -> None:
    with pytest.raises(AnswerValidationError):
        parse_grounded_answer(
            {"abstain": False, "claims": claims},
            [chunk("chunk-1", "C1")],
        )


def test_malformed_model_output_is_rejected() -> None:
    with pytest.raises(AnswerValidationError, match="invalid grounded answer"):
        parse_grounded_answer({"claims": "not a list"}, [chunk("chunk-1", "C1")])


def test_answer_rejects_too_many_or_oversized_claims() -> None:
    retrieved = [chunk("chunk-1", "C1")]
    oversized = [{"text": "x" * 2001, "refs": ["C1"]}]
    too_many = [{"text": "Claim.", "refs": ["C1"]} for _ in range(21)]

    with pytest.raises(AnswerValidationError):
        parse_grounded_answer({"abstain": False, "claims": oversized}, retrieved)
    with pytest.raises(AnswerValidationError):
        parse_grounded_answer({"abstain": False, "claims": too_many}, retrieved)