import pytest

from rag.retrieval.answer import (
    AnswerValidationError,
    parse_grounded_investigation,
)
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


def test_parse_grounded_investigation_preserves_validated_structure() -> None:
    answer = parse_grounded_investigation(
        {
            "abstain": False,
            "summary": {
                "text": "The policy includes flood cover subject to limits.",
                "refs": ["C1"],
            },
            "findings": [
                {"text": "Flood damage is covered subject to the stated limits.", "refs": ["C1"]}
            ],
            "unresolved_questions": ["What is the estimated repair cost?"],
        },
        [retrieved_chunk()],
    )

    assert answer.status == "answered"
    assert answer.summary == "The policy includes flood cover subject to limits."
    assert answer.summary_refs == ("C1",)
    assert answer.findings[0].text == "Flood damage is covered subject to the stated limits."
    assert answer.findings[0].refs == ("C1",)
    assert answer.unresolved_questions == ("What is the estimated repair cost?",)
    assert [citation.chunk_id for citation in answer.citations] == ["chunk-1"]


def test_parse_grounded_investigation_rejects_unknown_finding_refs() -> None:
    with pytest.raises(AnswerValidationError, match="invalid grounded investigation"):
        parse_grounded_investigation(
            {
                "summary": {"text": "Flood cover may apply.", "refs": ["C1"]},
                "findings": [{"text": "Flood cover applies.", "refs": ["C9"]}],
                "unresolved_questions": [],
            },
            [retrieved_chunk()],
        )


def test_parse_grounded_investigation_abstains_without_factual_findings() -> None:
    answer = parse_grounded_investigation(
        {
            "abstain": True,
            "summary": {"text": "", "refs": []},
            "findings": [],
            "unresolved_questions": ["Which rooms were affected?"],
        },
        [retrieved_chunk()],
    )

    assert answer.status == "insufficient_evidence"
    assert answer.summary == ""
    assert answer.summary_refs == ()
    assert answer.findings == ()
    assert answer.citations == []


def test_parse_grounded_investigation_rejects_assertions_as_questions() -> None:
    with pytest.raises(AnswerValidationError, match="invalid grounded investigation"):
        parse_grounded_investigation(
            {
                "abstain": True,
                "summary": {"text": "", "refs": []},
                "findings": [],
                "unresolved_questions": ["The policy covers flood damage."],
            },
            [retrieved_chunk()],
        )


@pytest.mark.parametrize(
    "question",
    [
        "How should we deny this claim?",
        "Is this claim covered?",
        "What do you advise?",
        "Would the insurer pay this claim?",
        "Is the insurer liable for this loss?",
        "Does this loss qualify for indemnity?",
        "Is this claim indemnifiable?",
        "Would the policy pay this claim?",
        "Does coverage apply?",
        "Is this covered?",
        "Will payment be issued on this claim?",
        "What is the repair estimate? Water entered the house?",
        "Will this claim be paid?",
        "Is there coverage for this loss?",
        "What coverage applies to this claim?",
    ],
)
def test_parse_grounded_investigation_rejects_decision_seeking_questions(
    question: str,
) -> None:
    with pytest.raises(AnswerValidationError, match="invalid grounded investigation"):
        parse_grounded_investigation(
            {
                "abstain": True,
                "summary": {"text": "", "refs": []},
                "findings": [],
                "unresolved_questions": [question],
            },
            [retrieved_chunk()],
        )


@pytest.mark.parametrize(
    "question",
    [
        "Does the claimant have repair estimates?",
        "What is the expected payment date?",
        "When was the insured paid?",
        "Was the claim paid on 12 June?",
        "What was the claim payment date?",
        "What advice did the policyholder receive from the broker?",
        "What recommendation did the broker make?",
    ],
)
def test_parse_grounded_investigation_accepts_yes_no_missing_fact_questions(
    question: str,
) -> None:
    answer = parse_grounded_investigation(
        {
            "abstain": True,
            "summary": {"text": "", "refs": []},
            "findings": [],
            "unresolved_questions": [question],
        },
        [retrieved_chunk()],
    )

    assert answer.unresolved_questions == (question,)


@pytest.mark.parametrize(
    "finding_text",
    [
        "The base wording excludes flood damage.",
        "Coverage does not extend to flood damage.",
        "The claimant obtained legal advice after the loss.",
    ],
)
def test_parse_grounded_investigation_accepts_neutral_policy_and_claim_facts(
    finding_text: str,
) -> None:
    answer = parse_grounded_investigation(
        {
            "abstain": False,
            "summary": {"text": "The policy excludes flood damage.", "refs": ["C1"]},
            "findings": [{"text": finding_text, "refs": ["C1"]}],
            "unresolved_questions": [],
        },
        [retrieved_chunk()],
    )

    assert answer.status == "answered"


@pytest.mark.parametrize(
    "finding_text",
    [
        "The claim should be denied.",
        "The claim is payable under this section.",
        "The claim is covered under the extension.",
        "The policy covers this claim.",
        "The insurer should pay this claim.",
        "We recommend denying this claim.",
        "A denial is warranted for this claim.",
        "A denial is appropriate for this claim.",
        "The claim is\npayable under the extension.",
        "The insurer is liable for this loss.",
        "This claim is indemnifiable.",
        "The claim is not eligible.",
        "The insured qualifies for compensation.",
        "The insurer will pay this claim.",
        "The insurer paid the claim.",
        "The policy will pay for this claim.",
        "The claim was paid.",
        "The claim falls within the flood extension.",
        "The claim falls in the flood extension.",
        "The claim is excluded under the policy.",
        "The claim falls outside the flood extension.",
        "The claim is subject to the flood exclusion.",
        "The policy excludes this loss.",
        "Coverage is triggered for this loss.",
        "Coverage applies to this loss.",
        "The insurer will pay the claim.",
    ],
)
def test_parse_grounded_investigation_rejects_coverage_decision_findings(
    finding_text: str,
) -> None:
    with pytest.raises(AnswerValidationError, match="invalid grounded investigation"):
        parse_grounded_investigation(
            {
                "abstain": False,
                "summary": {"text": "A policy term is relevant.", "refs": ["C1"]},
                "findings": [{"text": finding_text, "refs": ["C1"]}],
                "unresolved_questions": [],
            },
            [retrieved_chunk()],
        )


@pytest.mark.parametrize(
    "payload",
    [
        {
            "abstain": False,
            "summary": {"text": "A summary without citations.", "refs": []},
            "findings": [{"text": "A finding.", "refs": ["C1"]}],
            "unresolved_questions": [],
        },
        {
            "abstain": False,
            "summary": {"text": "A summary.", "refs": ["C1"]},
            "findings": [],
            "unresolved_questions": [],
        },
    ],
)
def test_parse_grounded_investigation_rejects_ungrounded_or_empty_briefs(
    payload: dict[str, object],
) -> None:
    with pytest.raises(AnswerValidationError, match="invalid grounded investigation"):
        parse_grounded_investigation(payload, [retrieved_chunk()])