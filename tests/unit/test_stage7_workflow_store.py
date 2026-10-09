"""Tests for Stage 7 workflow state and persistence contracts."""

from pathlib import Path
import sys
from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

API_MODULE_DIR = Path(__file__).resolve().parents[2] / "apps" / "ai-api"
sys.path.insert(0, str(API_MODULE_DIR))

from workflow_store import (
    WorkflowStore,
    compact_investigation_result,
    disposition_transition,
    retains_request_payload,
    resume_transition,
)
from agents.claims.models import (
    ClaimsWorkflowCreateInput,
    ClaimsWorkflowDispositionInput,
    ClaimsWorkflowResumeInput,
)


def test_serialize_converts_database_uuid_to_string() -> None:
    workflow_id = UUID("6386ce12-e996-4f0f-b1c6-18907e6b6839")
    timestamp = datetime.now(UTC)

    serialized = WorkflowStore._serialize(
        {
            "workflow_id": workflow_id,
            "claim_id": "CL-125",
            "state": "failed",
            "version": 2,
            "created_at": timestamp,
            "updated_at": timestamp,
            "error_code": "stage6_dependency_failed",
            "result": None,
        }
    )

    assert serialized["workflow_id"] == str(workflow_id)


@pytest.mark.parametrize(
    ("disposition", "expected_state"),
    [
        ("continue", "completed"),
        ("request_info", "needs_more_information"),
        ("stop", "cancelled"),
    ],
)
def test_valid_disposition_transitions(disposition: str, expected_state: str) -> None:
    assert disposition_transition("awaiting_human_review", disposition) == expected_state


def test_disposition_is_rejected_from_non_review_state() -> None:
    with pytest.raises(ValueError, match="awaiting_human_review"):
        disposition_transition("investigating", "continue")


def test_unknown_disposition_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported disposition"):
        disposition_transition("awaiting_human_review", "approve_claim")


def test_resume_requires_information_state() -> None:
    assert resume_transition("needs_more_information") == "created"
    with pytest.raises(ValueError, match="needs_more_information"):
        resume_transition("completed")


def test_workflow_create_input_is_strict_and_bounded() -> None:
    request = ClaimsWorkflowCreateInput(
        claim_id="CL-125",
        narrative="Water entered the ground floor overnight.",
    )
    assert request.claim_id == "CL-125"
    with pytest.raises(ValidationError):
        ClaimsWorkflowCreateInput(
            claim_id="../private",
            narrative="Water entered the ground floor overnight.",
        )
    with pytest.raises(ValidationError):
        ClaimsWorkflowCreateInput(
            claim_id="CL-125",
            narrative="Water entered the ground floor overnight.",
            coverage_decision="approve",
        )


def test_disposition_and_resume_require_human_audit_fields() -> None:
    decision = ClaimsWorkflowDispositionInput(
        disposition="request_info",
        expected_version=1,
        actor_id="synthetic-handler-1",
        reason="Need schedule details",
    )
    assert decision.disposition == "request_info"
    resume = ClaimsWorkflowResumeInput(
        expected_version=2,
        actor_id="synthetic-handler-1",
        reason="Information received",
        updated_narrative="The flood extension is listed on the schedule.",
    )
    assert resume.updated_narrative.startswith("The flood extension")


def test_compact_result_strips_evidence_payloads() -> None:
    compact = compact_investigation_result(
        {
            "claim_id": "CL-125",
            "policy_id": "HOME-002",
            "loss_date": "2025-03-01",
            "guidance_as_of": "2025-03-01",
            "policy_evidence_status": "retrieved",
            "policy_evidence_unavailable_reason": None,
            "investigation": {
                "claim_id": "CL-125",
                "status": "answered",
                "summary": "Review summary",
                "summary_source_ids": ["policy_evidence:chunk-1"],
                "findings": [
                    {"text": "Finding", "source_ids": ["policy_evidence:chunk-1"]}
                ],
                "unresolved_questions": [],
                "sources": [
                    {
                        "source_id": "policy_evidence:chunk-1",
                        "source_type": "policy_evidence",
                        "facts": {"text": "FULL POLICY EVIDENCE MUST NOT PERSIST"},
                    }
                ],
                "model": "test-model",
                "tool_calls": 1,
                "latency_ms": 50,
                "trace_id": "a" * 32,
            },
            "risk_assessment": {
                "status": "unavailable",
                "priority_band": None,
                "handler_triage_required": None,
                "triage_reason": None,
                "model_version": None,
                "unavailable_reason": "risk_service_unavailable",
            },
            "latency_ms": 100,
            "trace_id": "a" * 32,
        }
    )
    serialized = str(compact)
    assert "Review summary" in serialized
    assert "policy_evidence:chunk-1" in serialized
    assert "FULL POLICY EVIDENCE MUST NOT PERSIST" not in serialized
    assert "facts" not in serialized


@pytest.mark.parametrize("state", ["created", "investigating", "awaiting_human_review", "needs_more_information"])
def test_narrative_is_retained_while_workflow_can_resume(state: str) -> None:
    assert retains_request_payload(state) is True


@pytest.mark.parametrize("state", ["completed", "failed", "cancelled"])
def test_narrative_is_cleared_for_terminal_workflows(state: str) -> None:
    assert retains_request_payload(state) is False