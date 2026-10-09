"""Run persisted claims workflows once, with restart-safe state transitions."""

from __future__ import annotations

import logging
from threading import Event, Thread
from time import monotonic
from typing import Any, Callable

from opentelemetry import trace

from agents.claims.runner import AgentOutputError

from workflow_store import WorkflowStore


logger = logging.getLogger("ai-api.workflow-worker")
tracer = trace.get_tracer(__name__)


class WorkflowWorker:
    """Claim queued workflows and execute each external investigation once."""

    def __init__(
        self,
        store: WorkflowStore,
        investigator: Callable[[dict[str, Any]], dict[str, Any]],
        *,
        poll_interval: float = 0.5,
    ) -> None:
        self._store = store
        self._investigator = investigator
        self._poll_interval = poll_interval
        self._stop_event = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        self._store.verify_schema()
        self._stop_event.clear()
        self._thread = Thread(target=self._run, name="claims-workflow-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
            if self._thread.is_alive():
                raise RuntimeError("Claims workflow worker did not stop cleanly")
            self._thread = None

    def process_once(self) -> bool:
        workflow = self._store.claim_next()
        if workflow is None:
            return False

        workflow_id = workflow["workflow_id"]
        with tracer.start_as_current_span("claims.workflow_stage6") as span:
            span.set_attribute("workflow.id", workflow_id)
            try:
                result = self._investigator(workflow["request_payload"])
                self._store.complete_investigation(workflow_id, result)
                span.set_attribute("workflow.outcome", "awaiting_human_review")
            except AgentOutputError:
                self._store.fail_investigation(workflow_id, "stage6_response_invalid")
                span.set_attribute("workflow.outcome", "stage6_response_invalid")
                logger.warning("Workflow result invalid workflow_id=%s", workflow_id)
            except Exception as error:
                self._store.fail_investigation(workflow_id, "stage6_dependency_failed")
                span.set_attribute("workflow.outcome", "stage6_dependency_failed")
                logger.warning(
                    "Workflow dependency failed workflow_id=%s error_type=%s",
                    workflow_id,
                    type(error).__name__,
                )
        return True

    def _run(self) -> None:
        worker_lock = None
        recovered = False
        try:
            while not self._stop_event.is_set():
                if worker_lock is None:
                    try:
                        worker_lock = self._store.acquire_worker_lock()
                    except Exception as error:
                        logger.warning(
                            "Workflow lock check failed error_type=%s",
                            type(error).__name__,
                        )
                    if worker_lock is None:
                        self._stop_event.wait(self._poll_interval)
                        continue
                if not recovered:
                    try:
                        interrupted = self._store.recover_interrupted_workflows()
                    except Exception as error:
                        logger.warning(
                            "Workflow recovery failed error_type=%s",
                            type(error).__name__,
                        )
                        worker_lock.close()
                        worker_lock = None
                        self._stop_event.wait(self._poll_interval)
                        continue
                    if interrupted:
                        logger.warning("Marked %d interrupted workflows as failed", interrupted)
                    recovered = True
                started = monotonic()
                try:
                    claimed = self.process_once()
                except Exception as error:
                    logger.warning("Workflow poll failed error_type=%s", type(error).__name__)
                    worker_lock.close()
                    worker_lock = None
                    recovered = False
                    claimed = False
                if not claimed:
                    elapsed = monotonic() - started
                    self._stop_event.wait(max(0, self._poll_interval - elapsed))
        finally:
            if worker_lock is not None:
                worker_lock.close()