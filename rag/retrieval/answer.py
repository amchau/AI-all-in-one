from __future__ import annotations

import re
from typing import Any

from rag.retrieval.models import GroundedAnswer, RetrievedChunk


_INLINE_REF_PATTERN = re.compile(r"\[C\d+\]")
_MAX_CLAIMS = 20
_MAX_CLAIM_CHARACTERS = 2000
_MAX_ANSWER_CHARACTERS = 8000


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