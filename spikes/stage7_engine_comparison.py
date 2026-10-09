"""Run isolated persistence checks for the Stage 7 workflow-engine comparison."""

from __future__ import annotations

import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from threading import Barrier
import uuid
from typing import Any

from psycopg import Connection, connect, sql
from psycopg.types.json import Jsonb


DISPOSITION_STATES = {
    "continue": "completed",
    "request_info": "needs_more_information",
    "stop": "cancelled",
}


def apply_disposition(state: str, disposition: str) -> str:
    """Validate and apply a human disposition to a waiting workflow."""
    if state != "awaiting_human_review":
        raise ValueError("Disposition is allowed only from awaiting_human_review")
    try:
        return DISPOSITION_STATES[disposition]
    except KeyError as error:
        raise ValueError(f"Unsupported disposition: {disposition}") from error


def resume_for_information(state: str) -> str:
    """Require an explicit human action to resume an information request."""
    if state != "needs_more_information":
        raise ValueError("Resume is allowed only from needs_more_information")
    return "awaiting_human_review"


def action_fingerprint(action: dict[str, Any]) -> str:
    """Build a stable fingerprint for idempotent action comparisons."""
    canonical = json.dumps(action, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def resolve_idempotent_replay(
    previous_fingerprint: str,
    previous_response: dict[str, Any],
    action: dict[str, Any],
) -> dict[str, Any]:
    """Return a prior action response only when the request payload matches."""
    if previous_fingerprint != action_fingerprint(action):
        raise ValueError("Idempotency key reused for a different action")
    return previous_response


def _create_schema(connection: Connection[Any], schema: str) -> None:
    schema_id = sql.Identifier(schema)
    connection.execute(sql.SQL("CREATE SCHEMA {}").format(schema_id))
    connection.execute(
        sql.SQL(
            """
            CREATE TABLE {}.workflow_state (
                workflow_id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                version INTEGER NOT NULL,
                request_payload JSONB NOT NULL,
                result JSONB
            )
            """
        ).format(schema_id)
    )
    connection.execute(
        sql.SQL(
            """
            CREATE TABLE {}.idempotency (
                key TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL,
                response JSONB NOT NULL
            )
            """
        ).format(schema_id)
    )
    connection.execute(
        sql.SQL(
            """
            CREATE TABLE {}.audit (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                state TEXT NOT NULL,
                disposition TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                reason TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        ).format(schema_id)
    )


def _update_workflow(
    connection: Connection[Any],
    schema: str,
    workflow_id: str,
    *,
    action: str,
    expected_version: int,
    idempotency_key: str,
    actor_id: str,
    reason: str,
    disposition: str | None = None,
) -> dict[str, Any]:
    schema_id = sql.Identifier(schema)
    fingerprint = action_fingerprint(
        {
            "workflow_id": workflow_id,
            "action": action,
            "expected_version": expected_version,
            "actor_id": actor_id,
            "reason": reason,
            "disposition": disposition,
        }
    )
    with connection.transaction():
        row = connection.execute(
            sql.SQL(
                "SELECT state, version FROM {}.workflow_state "
                "WHERE workflow_id = %s FOR UPDATE"
            ).format(schema_id),
            (workflow_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Workflow not found")
        state, version = row
        previous = connection.execute(
            sql.SQL("SELECT fingerprint, response FROM {}.idempotency WHERE key = %s").format(
                schema_id
            ),
            (idempotency_key,),
        ).fetchone()
        if previous is not None:
            action = {
                "workflow_id": workflow_id,
                "action": action,
                "expected_version": expected_version,
                "actor_id": actor_id,
                "reason": reason,
                "disposition": disposition,
            }
            return resolve_idempotent_replay(previous[0], previous[1], action)
        if version != expected_version:
            raise ValueError("Stale workflow version")
        next_state = (
            apply_disposition(state, disposition)
            if action == "disposition" and disposition is not None
            else resume_for_information(state)
        )
        response = {"state": next_state, "version": version + 1}
        connection.execute(
            sql.SQL(
                "UPDATE {}.workflow_state SET state = %s, version = %s "
                "WHERE workflow_id = %s"
            ).format(schema_id),
            (next_state, response["version"], workflow_id),
        )
        connection.execute(
            sql.SQL(
                "INSERT INTO {}.idempotency (key, fingerprint, response) "
                "VALUES (%s, %s, %s)"
            ).format(schema_id),
            (idempotency_key, fingerprint, Jsonb(response)),
        )
        connection.execute(
            sql.SQL(
                "INSERT INTO {}.audit "
                "(workflow_id, state, disposition, actor_id, reason) "
                "VALUES (%s, %s, %s, %s, %s)"
            ).format(schema_id),
            (workflow_id, next_state, action, actor_id, reason),
        )
        return response


def run_postgres_spike(dsn: str) -> dict[str, Any]:
    """Exercise queued recovery, human wait, idempotency, and explicit resume."""
    schema = f"stage7_spike_{uuid.uuid4().hex[:12]}"
    workflow_id = str(uuid.uuid4())
    result: dict[str, Any] = {"engine": "postgres", "workflow_id": workflow_id}
    try:
        with connect(dsn, autocommit=True) as connection:
            _create_schema(connection, schema)
            connection.execute(
                sql.SQL(
                    "INSERT INTO {}.workflow_state "
                    "(workflow_id, state, version, request_payload) "
                    "VALUES (%s, 'investigating', 0, %s)"
                ).format(sql.Identifier(schema)),
                (
                    workflow_id,
                    Jsonb({"claim_id": "CL-125", "narrative": "synthetic spike input"}),
                ),
            )

        with connect(dsn) as restarted_worker_connection:
            queued = restarted_worker_connection.execute(
                sql.SQL(
                    "SELECT state, request_payload FROM {}.workflow_state "
                    "WHERE workflow_id = %s"
                ).format(sql.Identifier(schema)),
                (workflow_id,),
            ).fetchone()
            if queued is None or queued[0] != "investigating":
                raise RuntimeError("Queued workflow was not recovered after reconnect")
            restarted_worker_connection.execute(
                sql.SQL(
                    "UPDATE {}.workflow_state "
                    "SET state = 'awaiting_human_review', version = 1, result = %s "
                    "WHERE workflow_id = %s"
                ).format(sql.Identifier(schema)),
                (Jsonb({"adapter": "deterministic_fake", "status": "answered"}), workflow_id),
            )
        result["queued_recovery"] = True

        with connect(dsn) as decision_connection:
            review = decision_connection.execute(
                sql.SQL(
                    "SELECT state, version FROM {}.workflow_state WHERE workflow_id = %s"
                ).format(sql.Identifier(schema)),
                (workflow_id,),
            ).fetchone()
            if review != ("awaiting_human_review", 1):
                raise RuntimeError("Human wait state was not durable")
            barrier = Barrier(2)

            def submit_same_action() -> dict[str, Any]:
                with connect(dsn) as concurrent_connection:
                    barrier.wait(timeout=5)
                    return _update_workflow(
                        concurrent_connection,
                        schema,
                        workflow_id,
                        action="disposition",
                        expected_version=1,
                        idempotency_key="request-info-1",
                        actor_id="synthetic-reviewer-1",
                        reason="Need schedule details",
                        disposition="request_info",
                    )

            with ThreadPoolExecutor(max_workers=2) as executor:
                submissions = [executor.submit(submit_same_action) for _ in range(2)]
                first, duplicate = (submission.result() for submission in submissions)
            if first != duplicate:
                raise RuntimeError("Concurrent idempotency replay changed the response")
            try:
                _update_workflow(
                    decision_connection,
                    schema,
                    workflow_id,
                    action="disposition",
                    expected_version=1,
                    idempotency_key="request-info-1",
                    actor_id="synthetic-reviewer-1",
                    reason="Conflicting action",
                    disposition="stop",
                )
            except ValueError as error:
                if "different action" not in str(error):
                    raise
            else:
                raise RuntimeError("Conflicting idempotency key reuse was accepted")
            try:
                _update_workflow(
                    decision_connection,
                    schema,
                    workflow_id,
                    action="disposition",
                    expected_version=1,
                    idempotency_key="stale-decision-1",
                    actor_id="synthetic-reviewer-1",
                    reason="Stale request",
                    disposition="continue",
                )
            except ValueError as error:
                if "Stale" not in str(error):
                    raise
            else:
                raise RuntimeError("Stale decision unexpectedly advanced the workflow")
            resumed = _update_workflow(
                decision_connection,
                schema,
                workflow_id,
                action="resume",
                expected_version=2,
                idempotency_key="resume-1",
                actor_id="synthetic-reviewer-1",
                reason="Information received",
            )
            completed = _update_workflow(
                decision_connection,
                schema,
                workflow_id,
                action="disposition",
                expected_version=resumed["version"],
                idempotency_key="continue-1",
                actor_id="synthetic-reviewer-1",
                reason="Continue workflow",
                disposition="continue",
            )
            audit_rows = decision_connection.execute(
                sql.SQL("SELECT to_jsonb(audit) FROM {}.audit").format(sql.Identifier(schema))
            ).fetchall()
            if any("narrative" in json.dumps(row[0]).lower() for row in audit_rows):
                raise RuntimeError("Narrative appeared in the audit table")
            result.update(
                {
                    "disposition": first,
                    "explicit_resume": resumed,
                    "completed": completed,
                    "concurrent_idempotency": True,
                    "conflicting_idempotency_rejected": True,
                    "stale_rejected": True,
                    "audit_excludes_narrative": True,
                }
            )
        return result
    finally:
        with connect(dsn, autocommit=True) as cleanup_connection:
            cleanup_connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema))
            )


async def run_temporal_spike(address: str) -> dict[str, Any]:
    """Exercise a durable human wait, worker restart, and workflow updates."""
    from spikes.stage7_temporal_spike import run_temporal_spike as run_temporal_probe

    return await run_temporal_probe(address)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("engine", choices=("postgres", "temporal"))
    parser.add_argument("--temporal-address", default="localhost:17233")
    arguments = parser.parse_args()
    if arguments.engine == "temporal":
        result = asyncio.run(run_temporal_spike(arguments.temporal_address))
    else:
        required = ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD")
        missing = [key for key in required if not os.environ.get(key)]
        if missing:
            raise SystemExit(f"Missing required environment variables: {', '.join(missing)}")
        from psycopg.conninfo import make_conninfo

        dsn = make_conninfo(
            host=os.environ.get("POSTGRES_HOST", "127.0.0.1"),
            port=os.environ.get("POSTGRES_PORT", "15432"),
            dbname=os.environ["POSTGRES_DB"],
            user=os.environ["POSTGRES_USER"],
            password=os.environ["POSTGRES_PASSWORD"],
            connect_timeout=5,
        )
        result = run_postgres_spike(dsn)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()