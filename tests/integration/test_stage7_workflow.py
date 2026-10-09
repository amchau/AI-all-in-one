"""Integration tests for durable Stage 7 workflows in a local Postgres database."""

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import sys
from threading import Barrier
from uuid import uuid4

import pytest

API_MODULE_DIR = Path(__file__).resolve().parents[2] / "apps" / "ai-api"
sys.path.insert(0, str(API_MODULE_DIR))
from workflow_store import WorkflowConflict, WorkflowStore


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_STAGE7_WORKFLOW_INTEGRATION") != "1",
    reason="set RUN_STAGE7_WORKFLOW_INTEGRATION=1 and STAGE7_WORKFLOW_DSN for local Postgres",
)


def make_store() -> WorkflowStore:
    dsn = os.getenv("STAGE7_WORKFLOW_DSN", "")
    if not dsn:
        pytest.fail("STAGE7_WORKFLOW_DSN is required for the Stage 7 integration test")
    store = WorkflowStore(dsn)
    store.verify_schema()
    return store


def make_result(claim_id: str) -> dict:
    return {
        "claim_id": claim_id,
        "policy_id": "HOME-002",
        "loss_date": "2025-03-01",
        "guidance_as_of": "2025-03-01",
        "policy_evidence_status": "retrieved",
        "policy_evidence_unavailable_reason": None,
        "investigation": {
            "claim_id": claim_id,
            "status": "answered",
            "summary": "Synthetic review summary.",
            "summary_source_ids": ["policy_evidence:chunk-1"],
            "findings": [
                {"text": "Synthetic finding.", "source_ids": ["policy_evidence:chunk-1"]}
            ],
            "unresolved_questions": ["Confirm the schedule."],
            "sources": [
                {
                    "source_id": "policy_evidence:chunk-1",
                    "source_type": "policy_evidence",
                    "facts": {"text": "Synthetic policy text not persisted."},
                }
            ],
            "model": "synthetic-test-model",
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


def delete_workflow(store: WorkflowStore, workflow_id: str) -> None:
    with store._connect() as connection, connection.transaction():
        connection.execute(
            "DELETE FROM claims_workflow.idempotency WHERE workflow_id = %s",
            (workflow_id,),
        )
        connection.execute(
            "DELETE FROM claims_workflow.events WHERE workflow_id = %s",
            (workflow_id,),
        )
        connection.execute(
            "DELETE FROM claims_workflow.workflows WHERE workflow_id = %s",
            (workflow_id,),
        )


def test_workflow_transitions_are_idempotent_and_competing_decisions_are_serialized() -> None:
    store = make_store()
    workflow = store.create_workflow(
        {"claim_id": f"CL-{uuid4().hex[:8]}", "narrative": "Synthetic water loss details."}
    )
    workflow_id = workflow["workflow_id"]
    try:
        claimed = store.claim_next()
        assert claimed is not None and claimed["workflow_id"] == workflow_id
        store.complete_investigation(workflow_id, make_result(workflow["claim_id"]))

        first = store.submit_disposition(
            workflow_id,
            disposition="request_info",
            expected_version=2,
            idempotency_key="request-info-integration-1",
            actor_id="synthetic-handler-1",
            reason="Need schedule details",
        )
        duplicate = store.submit_disposition(
            workflow_id,
            disposition="request_info",
            expected_version=2,
            idempotency_key="request-info-integration-1",
            actor_id="synthetic-handler-1",
            reason="Need schedule details",
        )
        assert duplicate == first
        with pytest.raises(WorkflowConflict, match="different action"):
            store.submit_disposition(
                workflow_id,
                disposition="stop",
                expected_version=2,
                idempotency_key="request-info-integration-1",
                actor_id="synthetic-handler-1",
                reason="Conflicting action",
            )

        resumed = store.resume_for_information(
            workflow_id,
            expected_version=3,
            idempotency_key="resume-integration-1",
            actor_id="synthetic-handler-1",
            reason="Information received",
            updated_narrative="The extension is listed on the schedule.",
        )
        assert resumed["state"] == "created"
        claimed_again = store.claim_next()
        assert claimed_again is not None and claimed_again["workflow_id"] == workflow_id
        store.complete_investigation(workflow_id, make_result(workflow["claim_id"]))

        barrier = Barrier(2)

        def submit(disposition: str) -> str:
            barrier.wait(timeout=5)
            try:
                result = store.submit_disposition(
                    workflow_id,
                    disposition=disposition,
                    expected_version=6,
                    idempotency_key=f"decision-{disposition}-integration-1",
                    actor_id="synthetic-handler-1",
                    reason=f"Submit {disposition}",
                )
                return result["state"]
            except WorkflowConflict:
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(submit, ("continue", "stop")))
        assert outcomes.count("conflict") == 1
        assert sum(outcome in {"completed", "cancelled"} for outcome in outcomes) == 1

        status = store.get_workflow(workflow_id)
        assert status["state"] in {"completed", "cancelled"}
        assert status["result"]["investigation"]["summary"] == "Synthetic review summary."
        assert any(event["trace_id"] == "a" * 32 for event in status["history"])
        assert all("facts" not in str(event) for event in status["history"])
        with store._connect() as connection:
            payload = connection.execute(
                "SELECT request_payload FROM claims_workflow.workflows WHERE workflow_id = %s",
                (workflow_id,),
            ).fetchone()["request_payload"]
        assert payload is None
    finally:
        delete_workflow(store, workflow_id)


def test_interrupted_investigation_becomes_failed_without_retry() -> None:
    store = make_store()
    workflow = store.create_workflow(
        {"claim_id": f"CL-{uuid4().hex[:8]}", "narrative": "Synthetic interrupted details."}
    )
    workflow_id = workflow["workflow_id"]
    try:
        claimed = store.claim_next()
        assert claimed is not None and claimed["workflow_id"] == workflow_id
        assert store.recover_interrupted_workflows() == 1
        status = store.get_workflow(workflow_id)
        assert status["state"] == "failed"
        assert status["error_code"] == "worker_interrupted"
        with store._connect() as connection:
            payload = connection.execute(
                "SELECT request_payload FROM claims_workflow.workflows WHERE workflow_id = %s",
                (workflow_id,),
            ).fetchone()["request_payload"]
        assert payload is None
    finally:
        delete_workflow(store, workflow_id)