from __future__ import annotations

from datetime import date

from rag.retrieval.models import SourceDocument


class SourceResolutionError(ValueError):
    """Raised when policy and guidance sources cannot be selected safely."""


class NoApplicableBasePolicyError(SourceResolutionError):
    """Raised when no base policy applies on the requested loss date."""


class AmbiguousBasePolicyError(SourceResolutionError):
    """Raised when more than one base policy is effective on the latest date."""


def select_eligible_sources(
    documents: list[SourceDocument],
    *,
    policy_id: str,
    loss_date: date,
    guidance_as_of: date | None = None,
) -> list[SourceDocument]:
    if not policy_id.strip():
        raise SourceResolutionError("policy_id must be non-empty")
    guidance_date = guidance_as_of or loss_date

    eligible_policies = [
        document
        for document in documents
        if document.doc_type == "policy"
        and document.policy_id == policy_id
        and document.effective_date <= loss_date
    ]
    if not eligible_policies:
        raise NoApplicableBasePolicyError("no applicable base policy")

    latest_effective_date = max(
        document.effective_date for document in eligible_policies
    )
    latest_policies = [
        document
        for document in eligible_policies
        if document.effective_date == latest_effective_date
    ]
    if len(latest_policies) != 1:
        raise AmbiguousBasePolicyError("ambiguous base policy for loss date")
    base_policy = latest_policies[0]

    selected = [base_policy]
    selected.extend(
        document
        for document in documents
        if document.doc_type == "endorsement"
        and document.policy_id == policy_id
        and document.product == base_policy.product
        and document.effective_date <= loss_date
    )
    selected.extend(
        document
        for document in documents
        if document.doc_type in {"procedure", "regulation"}
        and document.effective_date <= guidance_date
        and document.policy_id in {None, policy_id}
        and document.product in {"all", base_policy.product}
    )

    type_order = {"policy": 0, "endorsement": 1, "procedure": 2, "regulation": 3}
    return sorted(
        selected,
        key=lambda document: (
            type_order[document.doc_type],
            document.effective_date,
            document.doc_id,
        ),
    )