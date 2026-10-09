"""Tests for the one-shot Stage 7 Postgres queue worker."""

from pathlib import Path
import sys
from typing import Any

API_MODULE_DIR = Path(__file__).resolve().parents[2] / "apps" / "ai-api"
sys.path.insert(0, str(API_MODULE_DIR))

from workflow_worker import WorkflowWorker


class FakeStore:
    def __init__(self) -> None:
        self.claims = [
            {
                "workflow_id": "workflow-1",
                "request_payload": {"claim_id": "CL-125", "narrative": "synthetic"},
            }
        ]
        self.completed: list[tuple[str, dict[str, Any]]] = []
        self.failed: list[tuple[str, str]] = []

    def claim_next(self) -> dict[str, Any] | None:
        return self.claims.pop(0) if self.claims else None

    def complete_investigation(self, workflow_id: str, result: dict[str, Any]) -> None:
        self.completed.append((workflow_id, result))

    def fail_investigation(self, workflow_id: str, error_code: str) -> None:
        self.failed.append((workflow_id, error_code))


def test_worker_processes_one_claim_and_persists_result() -> None:
    store = FakeStore()
    calls = []
    worker = WorkflowWorker(store, lambda payload: calls.append(payload) or {"summary": "brief"})

    assert worker.process_once() is True
    assert worker.process_once() is False
    assert calls == [{"claim_id": "CL-125", "narrative": "synthetic"}]
    assert store.completed == [("workflow-1", {"summary": "brief"})]
    assert store.failed == []


def test_worker_marks_failure_without_retry() -> None:
    store = FakeStore()
    calls = []

    def fail_investigation(payload: dict[str, Any]) -> dict[str, Any]:
        calls.append(payload)
        raise RuntimeError("provider details must not persist")

    worker = WorkflowWorker(store, fail_investigation)

    assert worker.process_once() is True
    assert worker.process_once() is False
    assert len(calls) == 1
    assert store.failed == [("workflow-1", "stage6_dependency_failed")]
    assert store.completed == []