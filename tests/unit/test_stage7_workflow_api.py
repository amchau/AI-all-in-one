"""API tests for Stage 7 workflow lifecycle routes."""

from datetime import UTC, datetime
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest

API_MODULE_DIR = Path(__file__).resolve().parents[2] / "apps" / "ai-api"
sys.path.insert(0, str(API_MODULE_DIR))
with patch.dict(os.environ, {"AI_API_ENV_FILE": ""}), patch(
    "opentelemetry.sdk.trace.TracerProvider.add_span_processor"
):
    import main


class FakeWorkflowStore:
    def __init__(self) -> None:
        self.workflows: dict[str, dict] = {}

    def verify_schema(self) -> None:
        return None

    def create_workflow(self, request_payload: dict) -> dict:
        workflow = {
            "workflow_id": "11111111-1111-4111-8111-111111111111",
            "claim_id": request_payload["claim_id"],
            "state": "created",
            "version": 0,
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
            "error_code": None,
            "result": None,
            "history": [],
        }
        self.workflows[workflow["workflow_id"]] = workflow
        return workflow

    def get_workflow(self, workflow_id: str) -> dict:
        if workflow_id not in self.workflows:
            from workflow_store import WorkflowNotFound

            raise WorkflowNotFound()
        return self.workflows[workflow_id]

    def submit_disposition(self, workflow_id: str, **kwargs) -> dict:
        workflow = self.get_workflow(workflow_id)
        if kwargs["expected_version"] != workflow["version"]:
            from workflow_store import WorkflowConflict

            raise WorkflowConflict("Stale workflow version")
        workflow["state"] = {
            "continue": "completed",
            "request_info": "needs_more_information",
            "stop": "cancelled",
        }[kwargs["disposition"]]
        workflow["version"] += 1
        return {"state": workflow["state"], "version": workflow["version"]}

    def resume_for_information(self, workflow_id: str, **kwargs) -> dict:
        workflow = self.get_workflow(workflow_id)
        if workflow["state"] != "needs_more_information":
            from workflow_store import WorkflowConflict

            raise WorkflowConflict("Resume is allowed only from needs_more_information")
        workflow["state"] = "created"
        workflow["version"] += 1
        return {"state": workflow["state"], "version": workflow["version"]}


class FakeWorkflowWorker:
    def __init__(self, store, investigator) -> None:
        self.store = store

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None


@pytest.fixture
def workflow_client(monkeypatch):
    monkeypatch.setattr(main.settings, "postgres_query_password", "test-query-password")
    monkeypatch.setattr(main.settings, "postgres_workflow_password", "test-workflow-password")
    monkeypatch.setattr(main.settings, "litellm_master_key", "test-litellm-key")
    store = FakeWorkflowStore()
    monkeypatch.setattr(main, "create_workflow_store", lambda: store)
    monkeypatch.setattr(main, "WorkflowWorker", FakeWorkflowWorker)
    with TestClient(main.app) as client:
        yield client, store


def test_create_returns_persisted_identifier_without_narrative(workflow_client) -> None:
    client, _ = workflow_client
    narrative = "Water entered the ground floor overnight."
    response = client.post(
        "/v1/claims/workflows",
        json={"claim_id": "CL-125", "narrative": narrative},
    )

    assert response.status_code == 202
    assert response.json()["workflow_id"] == "11111111-1111-4111-8111-111111111111"
    assert response.json()["state"] == "created"
    assert narrative not in response.text


def test_status_route_returns_workflow_history(workflow_client) -> None:
    client, _ = workflow_client
    client.post(
        "/v1/claims/workflows",
        json={"claim_id": "CL-125", "narrative": "Water entered the ground floor overnight."},
    )

    response = client.get(
        "/v1/claims/workflows/11111111-1111-4111-8111-111111111111"
    )

    assert response.status_code == 200
    assert response.json()["claim_id"] == "CL-125"
    assert response.json()["history"] == []


def test_disposition_requires_idempotency_key_and_updates_state(workflow_client) -> None:
    client, store = workflow_client
    client.post(
        "/v1/claims/workflows",
        json={"claim_id": "CL-125", "narrative": "Water entered the ground floor overnight."},
    )
    store.workflows["11111111-1111-4111-8111-111111111111"].update(
        state="awaiting_human_review",
        version=2,
    )
    payload = {
        "disposition": "stop",
        "expected_version": 2,
        "actor_id": "synthetic-handler-1",
        "reason": "End this review flow",
    }
    endpoint = "/v1/claims/workflows/11111111-1111-4111-8111-111111111111/dispositions"
    assert client.post(endpoint, json=payload).status_code == 422

    response = client.post(
        endpoint,
        headers={"Idempotency-Key": "stop-decision-0001"},
        json=payload,
    )
    assert response.status_code == 200
    assert response.json()["state"] == "cancelled"


def test_missing_workflow_is_not_found(workflow_client) -> None:
    client, _ = workflow_client
    malformed = client.get("/v1/claims/workflows/not-a-uuid")
    assert malformed.status_code == 422
    response = client.get("/v1/claims/workflows/11111111-1111-4111-8111-222222222222")
    assert response.status_code == 404
    assert response.json()["detail"] == "Workflow not found"