"""Temporal-specific implementation for the isolated Stage 7 engine spike."""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from typing import Any

from temporalio import activity, workflow
from temporalio.client import Client, WorkflowUpdateFailedError
from temporalio.common import RetryPolicy
from temporalio.service import RPCError
from temporalio.worker import Worker

from spikes.stage7_engine_comparison import (
    action_fingerprint,
    apply_disposition,
    resolve_idempotent_replay,
    resume_for_information,
)


@activity.defn
async def fake_stage6(input_data: dict[str, str]) -> dict[str, str]:
    return {"adapter": "deterministic_fake", "status": "answered"}


@workflow.defn
class Stage7SpikeWorkflow:
    def __init__(self) -> None:
        self.state = "created"
        self.version = 0
        self.actions: dict[str, tuple[str, dict[str, Any]]] = {}
        self.investigation: dict[str, str] | None = None

    @workflow.run
    async def run(self, input_data: dict[str, str]) -> dict[str, Any]:
        self.state = "investigating"
        self.version = 1
        self.investigation = await workflow.execute_activity(
            fake_stage6,
            input_data,
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        self.state = "awaiting_human_review"
        self.version = 2
        await workflow.wait_condition(lambda: self.state in {"completed", "cancelled"})
        return self.snapshot()

    @workflow.query
    def snapshot(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "version": self.version,
            "investigation": self.investigation,
            "actions": self.actions,
        }

    @workflow.update
    def submit_disposition(self, action: dict[str, Any]) -> dict[str, Any]:
        prior = self.actions.get(action["idempotency_key"])
        if prior is not None:
            return resolve_idempotent_replay(prior[0], prior[1], action)
        if action["expected_version"] != self.version:
            raise ValueError("Stale workflow version")
        next_state = apply_disposition(self.state, action["disposition"])
        self.version += 1
        self.state = next_state
        response = {"state": self.state, "version": self.version}
        self.actions[action["idempotency_key"]] = (action_fingerprint(action), response)
        return response

    @submit_disposition.validator
    def validate_disposition(self, action: dict[str, Any]) -> None:
        prior = self.actions.get(action["idempotency_key"])
        if prior is not None:
            resolve_idempotent_replay(prior[0], prior[1], action)
            return
        if action["expected_version"] != self.version:
            raise ValueError("Stale workflow version")
        apply_disposition(self.state, action["disposition"])

    @workflow.update
    def resume_for_information(self, action: dict[str, Any]) -> dict[str, Any]:
        prior = self.actions.get(action["idempotency_key"])
        if prior is not None:
            return resolve_idempotent_replay(prior[0], prior[1], action)
        if action["expected_version"] != self.version:
            raise ValueError("Stale workflow version")
        self.state = resume_for_information(self.state)
        self.version += 1
        response = {"state": self.state, "version": self.version}
        self.actions[action["idempotency_key"]] = (action_fingerprint(action), response)
        return response

    @resume_for_information.validator
    def validate_resume(self, action: dict[str, Any]) -> None:
        prior = self.actions.get(action["idempotency_key"])
        if prior is not None:
            resolve_idempotent_replay(prior[0], prior[1], action)
            return
        if action["expected_version"] != self.version:
            raise ValueError("Stale workflow version")
        resume_for_information(self.state)


async def run_temporal_spike(address: str) -> dict[str, Any]:
    client = await Client.connect(address)
    task_queue = f"stage7-spike-{uuid.uuid4().hex}"
    workflow_id = str(uuid.uuid4())
    handle = await client.start_workflow(
        Stage7SpikeWorkflow.run,
        {"claim_id": "CL-125", "narrative": "synthetic spike input"},
        id=workflow_id,
        task_queue=task_queue,
    )

    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=[Stage7SpikeWorkflow],
        activities=[fake_stage6],
    )
    worker_task = asyncio.create_task(worker.run())
    try:
        for _ in range(200):
            try:
                state = await handle.query(Stage7SpikeWorkflow.snapshot)
                if state["state"] == "awaiting_human_review":
                    state_before_worker_stop = state
                    break
            except RPCError:
                pass
            await asyncio.sleep(0.1)
        else:
            raise TimeoutError("Temporal workflow did not reach its human wait")
    finally:
        await worker.shutdown()
        await worker_task

    restarted_worker = Worker(
        client,
        task_queue=task_queue,
        workflows=[Stage7SpikeWorkflow],
        activities=[fake_stage6],
    )
    restarted_task = asyncio.create_task(restarted_worker.run())
    try:
        for _ in range(200):
            try:
                recovered_state = await handle.query(Stage7SpikeWorkflow.snapshot)
                break
            except RPCError:
                await asyncio.sleep(0.1)
        else:
            raise TimeoutError("Restarted Temporal worker did not become available")
        if recovered_state["state"] != state_before_worker_stop["state"]:
            raise RuntimeError("Workflow state changed while its worker was stopped")

        request_info = {
            "disposition": "request_info",
            "expected_version": 2,
            "idempotency_key": "request-info-1",
            "actor_id": "synthetic-reviewer-1",
            "reason": "Need schedule details",
        }
        first = await handle.execute_update(
            Stage7SpikeWorkflow.submit_disposition,
            request_info,
            id="request-info-1",
        )
        duplicate = await handle.execute_update(
            Stage7SpikeWorkflow.submit_disposition,
            request_info,
            id="request-info-1",
        )
        if first != duplicate:
            raise RuntimeError("Duplicate Temporal update changed the response")

        try:
            await handle.execute_update(
                Stage7SpikeWorkflow.submit_disposition,
                {
                    **request_info,
                    "disposition": "stop",
                    "reason": "Conflicting action",
                },
                id="request-info-conflict-1",
            )
        except WorkflowUpdateFailedError as error:
            if "different action" not in str(error.cause):
                raise
        else:
            raise RuntimeError("Conflicting Temporal idempotency key reuse was accepted")

        try:
            await handle.execute_update(
                Stage7SpikeWorkflow.submit_disposition,
                {
                    **request_info,
                    "disposition": "continue",
                    "expected_version": 2,
                    "idempotency_key": "stale-decision-1",
                },
                id="stale-decision-1",
            )
        except WorkflowUpdateFailedError as error:
            if "Stale workflow version" not in str(error.cause):
                raise
        else:
            raise RuntimeError("Stale Temporal update unexpectedly advanced the workflow")

        resumed = await handle.execute_update(
            Stage7SpikeWorkflow.resume_for_information,
            {
                "expected_version": 3,
                "idempotency_key": "resume-1",
                "actor_id": "synthetic-reviewer-1",
                "reason": "Information received",
            },
            id="resume-1",
        )
        completed = await handle.execute_update(
            Stage7SpikeWorkflow.submit_disposition,
            {
                "disposition": "continue",
                "expected_version": resumed["version"],
                "idempotency_key": "continue-1",
                "actor_id": "synthetic-reviewer-1",
                "reason": "Continue workflow",
            },
            id="continue-1",
        )
        final = await asyncio.wait_for(handle.result(), timeout=10)
        return {
            "engine": "temporal",
            "workflow_id": workflow_id,
            "state_before_worker_restart": state_before_worker_stop["state"],
            "state_after_worker_restart": recovered_state["state"],
            "disposition": first,
            "explicit_resume": resumed,
            "completed": completed,
            "final": final["state"],
            "duplicate_idempotency": True,
            "stale_rejected": True,
            "activity_retry_policy": "maximum_attempts=1",
        }
    finally:
        await restarted_worker.shutdown()
        await restarted_task