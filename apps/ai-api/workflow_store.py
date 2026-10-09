"""Persist Stage 7 workflow state and minimal audit history in Postgres."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import uuid4

import psycopg
from psycopg import Connection, sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


WORKFLOW_SCHEMA = "claims_workflow"
WORKER_LOCK_ID = 7_201_009
DISPOSITION_STATES = {
    "continue": "completed",
    "request_info": "needs_more_information",
    "stop": "cancelled",
}


class WorkflowNotFound(Exception):
    """Raised when a workflow identifier does not exist."""


class WorkflowConflict(ValueError):
    """Raised when a workflow transition or idempotency request conflicts."""


def disposition_transition(state: str, disposition: str) -> str:
    """Validate and apply a human disposition to a waiting workflow."""
    if state != "awaiting_human_review":
        raise WorkflowConflict("Disposition is allowed only from awaiting_human_review")
    try:
        return DISPOSITION_STATES[disposition]
    except KeyError as error:
        raise ValueError(f"Unsupported disposition: {disposition}") from error


def resume_transition(state: str) -> str:
    """Require a human resume action before investigating new information."""
    if state != "needs_more_information":
        raise WorkflowConflict("Resume is allowed only from needs_more_information")
    return "created"


def retains_request_payload(state: str) -> bool:
    """Retain request data only while the workflow can still resume."""
    return state in {
        "created",
        "investigating",
        "awaiting_human_review",
        "needs_more_information",
    }


def _fingerprint(action: dict[str, Any]) -> str:
    canonical = json.dumps(action, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compact_investigation_result(result: dict[str, Any]) -> dict[str, Any]:
    """Retain handler review content and identifiers, but remove evidence payloads."""
    investigation = result["investigation"]
    sources = [
        {
            "source_id": source["source_id"],
            "source_type": source["source_type"],
        }
        for source in investigation["sources"]
    ]
    return {
        "claim_id": result["claim_id"],
        "policy_id": result["policy_id"],
        "loss_date": result["loss_date"],
        "guidance_as_of": result["guidance_as_of"],
        "policy_evidence_status": result["policy_evidence_status"],
        "policy_evidence_unavailable_reason": result["policy_evidence_unavailable_reason"],
        "investigation": {
            "claim_id": investigation["claim_id"],
            "status": investigation["status"],
            "summary": investigation["summary"],
            "summary_source_ids": investigation["summary_source_ids"],
            "findings": investigation["findings"],
            "unresolved_questions": investigation["unresolved_questions"],
            "sources": sources,
            "model": investigation["model"],
            "tool_calls": investigation["tool_calls"],
            "latency_ms": investigation["latency_ms"],
            "trace_id": investigation["trace_id"],
        },
        "risk_assessment": result["risk_assessment"],
        "latency_ms": result["latency_ms"],
        "trace_id": result["trace_id"],
    }


class WorkflowStore:
    """Database operations for one local synthetic workflow service."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._schema = sql.Identifier(WORKFLOW_SCHEMA)

    def _connect(self) -> Connection[dict[str, Any]]:
        return psycopg.connect(self._dsn, connect_timeout=3, row_factory=dict_row)

    def verify_schema(self) -> None:
        with self._connect() as connection:
            table = connection.execute(
                "SELECT to_regclass('claims_workflow.workflows') AS table_name"
            ).fetchone()
        if table is None or table["table_name"] is None:
            raise RuntimeError("Stage 7 workflow schema is not provisioned")

    def acquire_worker_lock(self) -> Connection[dict[str, Any]] | None:
        connection = self._connect()
        connection.autocommit = True
        lock = connection.execute(
            "SELECT pg_try_advisory_lock(%s) AS acquired",
            (WORKER_LOCK_ID,),
        ).fetchone()
        if lock is None or not lock["acquired"]:
            connection.close()
            return None
        return connection

    def create_workflow(self, request_payload: dict[str, Any]) -> dict[str, Any]:
        workflow_id = str(uuid4())
        with self._connect() as connection, connection.transaction():
            row = connection.execute(
                sql.SQL(
                    "INSERT INTO {}.workflows "
                    "(workflow_id, claim_id, state, version, request_payload) "
                    "VALUES (%s, %s, 'created', 0, %s) RETURNING *"
                ).format(self._schema),
                (
                    workflow_id,
                    request_payload["claim_id"],
                    Jsonb(request_payload),
                ),
            ).fetchone()
            self._append_event(
                connection,
                workflow_id,
                from_state=None,
                state="created",
                action="created",
                actor_id="system",
                reason="Workflow created",
            )
        return self._serialize(row)

    def get_workflow(self, workflow_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                sql.SQL("SELECT * FROM {}.workflows WHERE workflow_id = %s").format(
                    self._schema
                ),
                (workflow_id,),
            ).fetchone()
            if row is None:
                raise WorkflowNotFound(workflow_id)
            events = connection.execute(
                sql.SQL(
                    "SELECT event_id, from_state, state, action, disposition, actor_id, "
                    "reason, trace_id, created_at FROM {}.events WHERE workflow_id = %s "
                    "ORDER BY event_id"
                ).format(self._schema),
                (workflow_id,),
            ).fetchall()
        result = self._serialize(row)
        result["history"] = events
        return result

    def claim_next(self) -> dict[str, Any] | None:
        with self._connect() as connection, connection.transaction():
            row = connection.execute(
                sql.SQL(
                    "SELECT * FROM {}.workflows WHERE state = 'created' "
                    "ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED"
                ).format(self._schema)
            ).fetchone()
            if row is None:
                return None
            next_version = row["version"] + 1
            claimed = connection.execute(
                sql.SQL(
                    "UPDATE {}.workflows SET state = 'investigating', version = %s, "
                    "updated_at = NOW() WHERE workflow_id = %s RETURNING *"
                ).format(self._schema),
                (next_version, row["workflow_id"]),
            ).fetchone()
            self._append_event(
                connection,
                row["workflow_id"],
                from_state="created",
                state="investigating",
                action="investigation_started",
                actor_id="system",
                reason="Investigation started",
            )
        return self._serialize(claimed)

    def complete_investigation(
        self,
        workflow_id: str,
        result: dict[str, Any],
    ) -> None:
        compact_result = compact_investigation_result(result)
        self._finish_investigation(
            workflow_id,
            "awaiting_human_review",
            compact_result,
            None,
        )

    def fail_investigation(self, workflow_id: str, error_code: str) -> None:
        self._finish_investigation(workflow_id, "failed", None, error_code)

    def _finish_investigation(
        self,
        workflow_id: str,
        next_state: str,
        result: dict[str, Any] | None,
        error_code: str | None,
    ) -> None:
        with self._connect() as connection, connection.transaction():
            row = self._lock_workflow(connection, workflow_id)
            if row["state"] != "investigating":
                raise WorkflowConflict("Investigation is not in progress")
            connection.execute(
                sql.SQL(
                    "UPDATE {}.workflows SET state = %s, version = version + 1, "
                    "request_payload = CASE WHEN %s = 'failed' THEN NULL "
                    "ELSE request_payload END, result = %s, error_code = %s, updated_at = NOW() "
                    "WHERE workflow_id = %s"
                ).format(self._schema),
                (
                    next_state,
                    next_state,
                    Jsonb(result) if result is not None else None,
                    error_code,
                    workflow_id,
                ),
            )
            self._append_event(
                connection,
                workflow_id,
                from_state="investigating",
                state=next_state,
                action="investigation_finished" if result is not None else "investigation_failed",
                actor_id="system",
                reason="Investigation completed" if result is not None else error_code or "unavailable",
                trace_id=result.get("trace_id") if result is not None else None,
            )

    def submit_disposition(
        self,
        workflow_id: str,
        *,
        disposition: str,
        expected_version: int,
        idempotency_key: str,
        actor_id: str,
        reason: str,
    ) -> dict[str, Any]:
        action = {
            "kind": "disposition",
            "workflow_id": workflow_id,
            "disposition": disposition,
            "expected_version": expected_version,
            "actor_id": actor_id,
            "reason": reason,
        }
        return self._submit_action(
            workflow_id,
            action,
            idempotency_key,
            disposition=disposition,
        )

    def resume_for_information(
        self,
        workflow_id: str,
        *,
        expected_version: int,
        idempotency_key: str,
        actor_id: str,
        reason: str,
        updated_narrative: str,
    ) -> dict[str, Any]:
        action = {
            "kind": "resume",
            "workflow_id": workflow_id,
            "expected_version": expected_version,
            "actor_id": actor_id,
            "reason": reason,
            "updated_narrative": updated_narrative,
        }
        return self._submit_action(
            workflow_id,
            action,
            idempotency_key,
            updated_narrative=updated_narrative,
        )

    def _submit_action(
        self,
        workflow_id: str,
        action: dict[str, Any],
        idempotency_key: str,
        *,
        disposition: str | None = None,
        updated_narrative: str | None = None,
    ) -> dict[str, Any]:
        fingerprint = _fingerprint(action)
        with self._connect() as connection, connection.transaction():
            row = self._lock_workflow(connection, workflow_id)
            prior = connection.execute(
                sql.SQL(
                    "SELECT fingerprint, response FROM {}.idempotency "
                    "WHERE workflow_id = %s AND idempotency_key = %s"
                ).format(self._schema),
                (workflow_id, idempotency_key),
            ).fetchone()
            if prior is not None:
                if prior["fingerprint"] != fingerprint:
                    raise WorkflowConflict("Idempotency key reused for a different action")
                return prior["response"]
            if row["version"] != action["expected_version"]:
                raise WorkflowConflict("Stale workflow version")

            if disposition is not None:
                next_state = disposition_transition(row["state"], disposition)
                event_action = "disposition_submitted"
            else:
                next_state = resume_transition(row["state"])
                event_action = "request_information_resumed"
                request_payload = row["request_payload"]
                if updated_narrative is None or len(updated_narrative) > 1000:
                    raise WorkflowConflict("Updated narrative must not exceed 1,000 characters")
                request_payload["narrative"] = updated_narrative
                connection.execute(
                    sql.SQL(
                        "UPDATE {}.workflows SET request_payload = %s WHERE workflow_id = %s"
                    ).format(self._schema),
                    (Jsonb(request_payload), workflow_id),
                )

            response = {"state": next_state, "version": row["version"] + 1}
            connection.execute(
                sql.SQL(
                    "UPDATE {}.workflows SET state = %s, version = %s, error_code = NULL, "
                    "request_payload = CASE WHEN %s IN ('completed', 'failed', 'cancelled') "
                    "THEN NULL ELSE request_payload END, "
                    "result = CASE WHEN %s = 'created' THEN NULL ELSE result END, "
                    "updated_at = NOW() WHERE workflow_id = %s"
                ).format(self._schema),
                (next_state, response["version"], next_state, next_state, workflow_id),
            )
            connection.execute(
                sql.SQL(
                    "INSERT INTO {}.idempotency "
                    "(workflow_id, idempotency_key, fingerprint, response) "
                    "VALUES (%s, %s, %s, %s)"
                ).format(self._schema),
                (workflow_id, idempotency_key, fingerprint, Jsonb(response)),
            )
            self._append_event(
                connection,
                workflow_id,
                from_state=row["state"],
                state=next_state,
                action=event_action,
                disposition=disposition,
                actor_id=action["actor_id"],
                reason=action["reason"],
            )
        return response

    def recover_interrupted_workflows(self) -> int:
        recovered = 0
        with self._connect() as connection, connection.transaction():
            rows = connection.execute(
                sql.SQL(
                    "SELECT workflow_id FROM {}.workflows WHERE state = 'investigating' "
                    "FOR UPDATE"
                ).format(self._schema)
            ).fetchall()
            for row in rows:
                connection.execute(
                    sql.SQL(
                        "UPDATE {}.workflows SET state = 'failed', version = version + 1, "
                        "request_payload = NULL, error_code = 'worker_interrupted', "
                        "updated_at = NOW() "
                        "WHERE workflow_id = %s"
                    ).format(self._schema),
                    (row["workflow_id"],),
                )
                self._append_event(
                    connection,
                    row["workflow_id"],
                    from_state="investigating",
                    state="failed",
                    action="worker_interrupted",
                    actor_id="system",
                    reason="Worker stopped during investigation; no automatic retry",
                )
                recovered += 1
        return recovered

    def _lock_workflow(
        self,
        connection: Connection[dict[str, Any]],
        workflow_id: str,
    ) -> dict[str, Any]:
        row = connection.execute(
            sql.SQL("SELECT * FROM {}.workflows WHERE workflow_id = %s FOR UPDATE").format(
                self._schema
            ),
            (workflow_id,),
        ).fetchone()
        if row is None:
            raise WorkflowNotFound(workflow_id)
        return row

    def _append_event(
        self,
        connection: Connection[dict[str, Any]],
        workflow_id: str,
        *,
        from_state: str | None,
        state: str,
        action: str,
        actor_id: str,
        reason: str,
        disposition: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        connection.execute(
            sql.SQL(
                "INSERT INTO {}.events "
                "(workflow_id, from_state, state, action, disposition, actor_id, reason, trace_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
            ).format(self._schema),
            (workflow_id, from_state, state, action, disposition, actor_id, reason, trace_id),
        )

    @staticmethod
    def _serialize(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "workflow_id": str(row["workflow_id"]),
            "claim_id": row["claim_id"],
            "state": row["state"],
            "version": row["version"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "error_code": row["error_code"],
            "result": row["result"],
        }