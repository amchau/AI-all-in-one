from datetime import date

import pytest

from rag.retrieval.sources import (
    SourceDocument,
    SourceResolutionError,
    select_eligible_sources,
)


def source(
    doc_id: str,
    doc_type: str,
    *,
    policy_id: str | None,
    product: str,
    effective_date: date,
    version: str = "1.0",
) -> SourceDocument:
    return SourceDocument(
        doc_id=doc_id,
        doc_type=doc_type,
        policy_id=policy_id,
        product=product,
        effective_date=effective_date,
        version=version,
        acl="internal",
        title=doc_id,
    )


def test_selects_applicable_policy_endorsements_and_guidance_by_separate_dates() -> None:
    documents = [
        source("POL-OLD", "policy", policy_id="HOME-002", product="home", effective_date=date(2024, 1, 1)),
        source("POL-CURRENT", "policy", policy_id="HOME-002", product="home", effective_date=date(2025, 1, 1), version="2.0"),
        source("POL-FUTURE", "policy", policy_id="HOME-002", product="home", effective_date=date(2026, 1, 1), version="3.0"),
        source("END-VALID", "endorsement", policy_id="HOME-002", product="home", effective_date=date(2025, 2, 1)),
        source("END-FUTURE", "endorsement", policy_id="HOME-002", product="home", effective_date=date(2025, 4, 1)),
        source("END-OTHER", "endorsement", policy_id="MOTOR-001", product="motor", effective_date=date(2025, 1, 1)),
        source("PROC-HOME", "procedure", policy_id="HOME-002", product="home", effective_date=date(2025, 1, 1)),
        source("PROC-GLOBAL", "procedure", policy_id=None, product="all", effective_date=date(2025, 1, 1)),
        source("REG-FUTURE", "regulation", policy_id=None, product="all", effective_date=date(2026, 1, 1)),
        source("PROC-OTHER", "procedure", policy_id="MOTOR-001", product="motor", effective_date=date(2025, 1, 1)),
    ]

    eligible = select_eligible_sources(
        documents,
        policy_id="HOME-002",
        loss_date=date(2025, 3, 1),
        guidance_as_of=date(2026, 2, 1),
    )

    assert {document.doc_id for document in eligible} == {
        "POL-CURRENT",
        "END-VALID",
        "PROC-HOME",
        "PROC-GLOBAL",
        "REG-FUTURE",
    }


def test_guidance_date_defaults_to_loss_date() -> None:
    documents = [
        source("POL-CURRENT", "policy", policy_id="HOME-002", product="home", effective_date=date(2025, 1, 1)),
        source("REG-FUTURE", "regulation", policy_id=None, product="all", effective_date=date(2026, 1, 1)),
    ]

    eligible = select_eligible_sources(
        documents,
        policy_id="HOME-002",
        loss_date=date(2025, 3, 1),
    )

    assert [document.doc_id for document in eligible] == ["POL-CURRENT"]


def test_missing_applicable_base_policy_fails_closed() -> None:
    with pytest.raises(SourceResolutionError, match="no applicable base policy"):
        select_eligible_sources(
            [],
            policy_id="HOME-002",
            loss_date=date(2025, 3, 1),
        )


def test_ambiguous_latest_base_policy_fails_closed() -> None:
    documents = [
        source("POL-A", "policy", policy_id="HOME-002", product="home", effective_date=date(2025, 1, 1)),
        source("POL-B", "policy", policy_id="HOME-002", product="home", effective_date=date(2025, 1, 1), version="2.0"),
    ]

    with pytest.raises(SourceResolutionError, match="ambiguous base policy"):
        select_eligible_sources(
            documents,
            policy_id="HOME-002",
            loss_date=date(2025, 3, 1),
        )