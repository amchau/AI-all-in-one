from __future__ import annotations

import re
from typing import Any

from rag.retrieval.models import (
    GroundedAnswer,
    GroundedFinding,
    GroundedInvestigation,
    RetrievedChunk,
)


_INLINE_REF_PATTERN = re.compile(r"\[C\d+\]")
_MAX_CLAIMS = 20
_MAX_CLAIM_CHARACTERS = 2000
_MAX_ANSWER_CHARACTERS = 8000
_MAX_SUMMARY_CHARACTERS = 2000
_MAX_INVESTIGATION_FINDINGS = 8
_MAX_INVESTIGATION_CHARACTERS = 4000
_MAX_UNRESOLVED_QUESTIONS = 4
_MAX_UNRESOLVED_QUESTION_CHARACTERS = 160
_MISSING_FACT_QUESTION_PATTERN = re.compile(
    r"^(?:what|which|when|where|who|how|does|do|did|is|are|was|were|has|have|had|can|could|will|would|please confirm)\b",
    re.IGNORECASE,
)
_DECISION_SEEKING_QUESTION_PATTERN = re.compile(
    r"\b(?:should|approve|deny|decline|reject|decide|decision|settle(?:ment)?)\b|"
    r"\b(?:what do you|please|would you)\s+(?:advise|recommend)\b|"
    r"\bwhat is your recommendation\b",
    re.IGNORECASE,
)
_DECISION_OUTCOME_QUESTION_PATTERN = re.compile(
    r"\b(?:claim|loss|damage|insured|insurer)\b.{0,50}\b"
    r"(?:covered|payable|liable|liability|indemnifi\w*|qualif\w*|"
    r"eligib(?:le|ility)|entitled|indemnity|compensation|approve|deny|"
    r"decline|reject|settle)\b|"
    r"\b(?:will|would|should|could|can)\b.{0,20}\b(?:this|the|your)\s+(?:claim|loss|damage)\b.{0,20}\bbe\s+paid\b|"
    r"\b(?:this|the|your)\s+(?:claim|loss|damage)\b.{0,30}\b(?:will|would|should|could|can)\s+be\s+paid\b|"
    r"\b(?:will|would|should|could|can)\b.{0,50}\b(?:pay|paid)\b.{0,30}\b(?:this|the|your)\s+(?:claim|loss|damage)\b|"
    r"\bcoverage\b.{0,30}\bfor\b.{0,20}\b(?:this|the|your)\s+(?:claim|loss|damage)\b|"
    r"\b(?:does|do)\s+(?:coverage|insurance)\s+(?:apply|extend)\b|"
    r"\b(?:is|are)\s+(?:this|that)\s+(?:covered|insured)\b|"
    r"\b(?:will|would|should|could|can)\s+payment\b.{0,30}\b(?:claim|loss|damage)\b|"
    r"\bcoverage\b.{0,40}\b(?:applies|does not apply|is available|is excluded|"
    r"does not extend|extends|is triggered)\b.{0,30}\b(?:this|the|your)\s+(?:claim|loss|damage)\b|"
    r"\bpolicy\b.{0,40}\b(?:covers?|excludes?|denies?)\b.{0,30}\b(?:this|the|your)\s+(?:claim|loss|damage)\b",
    re.IGNORECASE,
)
_NON_DECISIONAL_STATEMENT_PATTERN = re.compile(
    r"\b(?:(?:this|the|your)\s+(?:claim|loss|incident|damage)|"
    r"(?:the\s+)?(?:insured|claimant))\b.{0,50}\b"
    r"(?:(?:is|are|was|were|will be|would be|may be|might be|should be)\s+)?"
    r"(?:covered|not covered|excluded|paid|payable|approved|denied|declined|rejected|settled|"
    r"(?:not\s+)?eligible|liable|indemnifi\w*|indemnified|compensated|qualif\w*|"
    r"falls?\s+(?:within|outside|under|in)|subject to\b.{0,30}\b(?:exclusion|extension|cover))|"
    r"\b(?:the\s+)?(?:insurer|policy|wording)\b.{0,40}\b"
    r"(?:(?:will|would|should|may|might|can|must)\s+)?"
    r"(?:pay|paid|pays|approve|deny|decline|reject|settle|indemnify|compensate)\b|"
    r"\b(?:the\s+)?insurer\b.{0,40}\b(?:is|are|was|were)\s+"
    r"(?:liable|responsible|at fault|obligated)\b|"
    r"\bcoverage\b.{0,40}\b(?:applies|does not apply|is available|is excluded|"
    r"does not extend|extends|is triggered)\b.{0,30}\b(?:this|the|your)\s+(?:claim|loss|damage)\b|"
    r"\b(?:the\s+)?policy\b.{0,40}\b(?:covers?|excludes?|denies?)\b.{0,30}\b(?:this|the|your)\s+(?:claim|loss|damage)\b|"
    r"\b(?:we|i|the assistant|the copilot)\b.{0,40}\b(?:recommend|advise)\b.{0,40}\b(?:claim|loss)\b|"
    r"\b(?:denial|approval|rejection)\b.{0,40}\b(?:warranted|recommended|appropriate)\b.{0,40}\b(?:claim|loss)\b",
    re.IGNORECASE,
)


class AnswerValidationError(ValueError):
    """Raised when generated claims cannot be grounded in retrieved chunks."""


def parse_grounded_answer(
    payload: Any,
    chunks: list[RetrievedChunk],
) -> GroundedAnswer:
    if not isinstance(payload, dict):
        raise AnswerValidationError("invalid grounded answer")
    abstain = payload.get("abstain")
    claims = payload.get("claims")
    if type(abstain) is not bool or not isinstance(claims, list):
        raise AnswerValidationError("invalid grounded answer")
    if abstain:
        return GroundedAnswer(
            status="insufficient_evidence",
            answer="",
            citations=[],
        )
    if not claims or len(claims) > _MAX_CLAIMS:
        raise AnswerValidationError("invalid grounded answer")

    chunks_by_ref = {chunk.ref: chunk for chunk in chunks}
    rendered_claims: list[str] = []
    cited_refs: list[str] = []
    for claim in claims:
        if not isinstance(claim, dict) or set(claim) != {"text", "refs"}:
            raise AnswerValidationError("invalid grounded answer")
        text = claim["text"]
        refs = claim["refs"]
        if (
            not isinstance(text, str)
            or not text.strip()
            or len(text) > _MAX_CLAIM_CHARACTERS
            or _INLINE_REF_PATTERN.search(text)
            or not isinstance(refs, list)
            or not refs
            or any(not isinstance(ref, str) or ref not in chunks_by_ref for ref in refs)
        ):
            raise AnswerValidationError("invalid grounded answer")
        unique_refs = list(dict.fromkeys(refs))
        rendered_refs = ", ".join(f"[{ref}]" for ref in unique_refs)
        rendered_claims.append(f"{text.strip()} {rendered_refs}")
        if sum(map(len, rendered_claims)) > _MAX_ANSWER_CHARACTERS:
            raise AnswerValidationError("invalid grounded answer")
        cited_refs.extend(unique_refs)

    citations = [chunks_by_ref[ref].citation() for ref in dict.fromkeys(cited_refs)]
    return GroundedAnswer(
        status="answered",
        answer="\n".join(rendered_claims),
        citations=citations,
    )


def parse_grounded_investigation(
    payload: Any,
    chunks: list[RetrievedChunk],
) -> GroundedInvestigation:
    if not isinstance(payload, dict) or set(payload) != {
        "abstain",
        "summary",
        "findings",
        "unresolved_questions",
    }:
        raise AnswerValidationError("invalid grounded investigation")

    abstain = payload["abstain"]
    summary = payload["summary"]
    findings = payload["findings"]
    unresolved_questions = payload["unresolved_questions"]
    if (
        type(abstain) is not bool
        or not isinstance(summary, dict)
        or set(summary) != {"text", "refs"}
        or not isinstance(findings, list)
        or not isinstance(unresolved_questions, list)
        or len(unresolved_questions) > _MAX_UNRESOLVED_QUESTIONS
    ):
        raise AnswerValidationError("invalid grounded investigation")

    if any(
        not isinstance(question, str)
        or not question.strip()
        or len(question) > _MAX_UNRESOLVED_QUESTION_CHARACTERS
        or not _MISSING_FACT_QUESTION_PATTERN.match(question.strip())
        or not question.strip().endswith("?")
            or question.count("?") != 1
            or any(mark in question for mark in (".", "!", "\n"))
            or _DECISION_SEEKING_QUESTION_PATTERN.search(question)
            or _DECISION_OUTCOME_QUESTION_PATTERN.search(question)
        for question in unresolved_questions
    ):
        raise AnswerValidationError("invalid grounded investigation")

    if abstain:
        if summary != {"text": "", "refs": []} or findings:
            raise AnswerValidationError("invalid grounded investigation")
        return GroundedInvestigation(
            status="insufficient_evidence",
            summary="",
            summary_refs=(),
            findings=(),
            unresolved_questions=tuple(question.strip() for question in unresolved_questions),
            citations=[],
        )

    summary_text = summary["text"]
    summary_refs = summary["refs"]
    if (
        not isinstance(summary_text, str)
        or not summary_text.strip()
        or len(summary_text) > _MAX_SUMMARY_CHARACTERS
        or _INLINE_REF_PATTERN.search(summary_text)
        or _NON_DECISIONAL_STATEMENT_PATTERN.search(summary_text)
        or not isinstance(summary_refs, list)
        or not summary_refs
        or len(findings) > _MAX_INVESTIGATION_FINDINGS
    ):
        raise AnswerValidationError("invalid grounded investigation")

    chunks_by_ref = {chunk.ref: chunk for chunk in chunks}
    validated_summary_refs = _validated_refs(summary_refs, chunks_by_ref)
    validated_findings: list[GroundedFinding] = []
    refs_in_order = list(validated_summary_refs)
    total_characters = len(summary_text)
    for finding in findings:
        if not isinstance(finding, dict) or set(finding) != {"text", "refs"}:
            raise AnswerValidationError("invalid grounded investigation")
        text = finding["text"]
        refs = finding["refs"]
        if (
            not isinstance(text, str)
            or not text.strip()
            or len(text) > _MAX_CLAIM_CHARACTERS
            or _INLINE_REF_PATTERN.search(text)
            or _NON_DECISIONAL_STATEMENT_PATTERN.search(text)
            or not isinstance(refs, list)
            or not refs
        ):
            raise AnswerValidationError("invalid grounded investigation")
        validated_refs = _validated_refs(refs, chunks_by_ref)
        validated_findings.append(
            GroundedFinding(text=text.strip(), refs=validated_refs)
        )
        refs_in_order.extend(validated_refs)
        total_characters += len(text)
        if total_characters > _MAX_INVESTIGATION_CHARACTERS:
            raise AnswerValidationError("invalid grounded investigation")

    if not validated_findings:
        raise AnswerValidationError("invalid grounded investigation")

    citations = [
        chunks_by_ref[ref].citation() for ref in dict.fromkeys(refs_in_order)
    ]
    return GroundedInvestigation(
        status="answered",
        summary=summary_text.strip(),
        summary_refs=validated_summary_refs,
        findings=tuple(validated_findings),
        unresolved_questions=tuple(question.strip() for question in unresolved_questions),
        citations=citations,
    )


def _validated_refs(
    refs: list[Any],
    chunks_by_ref: dict[str, RetrievedChunk],
) -> tuple[str, ...]:
    if any(not isinstance(ref, str) or ref not in chunks_by_ref for ref in refs):
        raise AnswerValidationError("invalid grounded investigation")
    return tuple(dict.fromkeys(refs))