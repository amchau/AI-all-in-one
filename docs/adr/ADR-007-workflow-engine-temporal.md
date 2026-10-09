# ADR-007 - Stage 7 Workflow Engine

## Status

Accepted 2026-10-09: Postgres-backed state machine for the local synthetic Stage 7 prototype.

## Context

Stage 7 adds a durable human checkpoint to the synthetic claims investigation workflow. The workflow must wait for a human, survive service/worker restarts, validate state transitions, and avoid treating a disposition as a claim or coverage decision. Stage 6 was accepted on 2026-10-08 for the reviewed local synthetic scope; its handoff documents the tested fixtures and limitations. Stage 7 may use the live Stage 6 endpoint for local end-to-end verification and must use a deterministic fake for isolated tests.

## Options

| Criterion | Temporal | Database-backed state machine | In-process workflow |
|---|---|---|---|
| Durable waits and restart recovery | Built-in workflow history/replay | Must be implemented and tested | Not durable across process restart |
| State transitions | Workflow code and signals | Explicit application logic and transaction boundaries | In-memory application logic |
| Timers/escalation | Built-in primitives | Requires scheduler/outbox or polling design | Not reliable across restart |
| Local kind complexity | Additional services/workers | Existing database plus application changes | Lowest |
| Learning value | Durable workflow concepts | Transparent mechanics and fewer dependencies | Limited to prototype behavior |
| Operational cost | Higher; validate resource footprint | Moderate; database lifecycle and locking | Low but fails durability goal |

## Decision

Use a Postgres-backed state machine in the local synthetic Stage 7 prototype. This matches the current scope, which has no timers or escalation, and reuses the existing Postgres service. Use a separate least-privilege workflow role and schema; never reuse `rag_query`. The workflow runs asynchronously in one API worker, persists state and audit transitions, and invokes Stage 6 once without automatic retries.

Planning constraints confirmed by the user:

- Workflow creation is asynchronous; invoke Stage 6 once without automatic retries.
- Dispositions are `continue` -> `completed`, `request_info` -> `needs_more_information` pending explicit human resume, and `stop` -> terminal `cancelled`.
- Use one synthetic reviewer, with no second reviewer, timer, or escalation. `actor_id` is audit metadata only and does not represent authenticated identity.
- Retain minimal audit history until local database teardown. Do not include narratives in audit records, API responses, logs, or telemetry. Keep narratives only in active/resumable workflow request payloads and clear them at terminal state. Persist a compact review result; exclude source facts and full evidence text.

## Feasibility Spike (2026-10-09)

The isolated spike artifacts are `spikes/stage7_engine_comparison.py`,
`spikes/stage7_temporal_spike.py`, and `tests/unit/test_stage7_engine_spike.py`. It used the same
disposition mapping and deterministic fake investigation for both candidates. Neither engine was
added to application requirements or deployed to the kind cluster. The Temporal probe used Python
3.12.13, `temporalio` 1.34.0, and Temporal CLI 1.9.1 (server 1.32.0).

| Check | Postgres-backed state | Temporal |
|---|---|---|
| Human wait and transitions | Passed: persisted waiting state, request-info, explicit resume, completion | Passed: durable update and workflow history, request-info, explicit resume, completion |
| Restart boundary | State was read after closing and reopening database connections; no worker process was killed | Worker instance was stopped and recreated; workflow returned to the same wait state |
| Idempotency and stale action | Two concurrent connections with the same key returned one consistent response; conflicting key reuse and stale version rejected | Repeated update ID returned original response; conflicting key reuse and stale version rejected by update validator |
| Narrative handling | Stored in request JSON; absent from audit rows; disposable schema dropped | Included in durable workflow input/history; no separate audit table in the spike |
| Local footprint | Reused the existing Postgres pod (100m CPU / 256MiB request; 500m / 512MiB limit); no new service | Temporal CLI 1.9.1 / server 1.32.0 used about 204 MiB RSS as a local dev process; not a measured production pod request |
| Extra operational work | Requires workflow tables, transaction/locking logic, and a separate least-privilege write role; spike ran as the local DB owner | Requires a Temporal server and worker lifecycle; no application DB schema or write credential for workflow state |

Temporal queries were unavailable while no worker polled the task queue and succeeded after the
worker restarted. This is a relevant operational difference for status inspection. The Postgres
probe's reconnect boundary is weaker than killing and restarting an OS worker process. The Postgres
probe raced exact duplicate submissions, but neither candidate raced two different dispositions
against the same version or tested a recoverable worker-claim lease, server restart, or
production-style retention cleanup. Treat these results as comparative evidence, not acceptance.

The user selected Postgres after reviewing the initial comparison. Temporal's built-in replay and
workflow history remain useful alternatives for a future scope with timers or richer orchestration,
but add a service and operational concepts not needed here. The initial spike did not prove
OS-level worker crash recovery. Live Postgres integration later verified competing dispositions
serialize to one winner, and the API has started successfully using the dedicated role. Process-kill
recovery and full deployed UI/API smoke remain acceptance gates.

## Validation

For the feasibility spike, test restart recovery at the human wait, duplicate/stale decision behavior, and a single Stage 6 dependency failure without retry. Measure local resource footprint and document operational steps. After engine and plan approval, test wait/resume across worker/API restarts, idempotent and stale decisions, illegal state transitions, cancellation semantics, Stage 6 dependency failure, and narrative exclusion from audit and telemetry. Do not use a real claim or imply production readiness.

## Consequences

- No production Stage 7 workflow implementation should begin until this ADR and the Stage 7 plan are approved. The isolated feasibility spike is the prerequisite to selecting the engine.
- Preserve claim-decision authority with the human and keep model outputs outside workflow control.
- Keep Stage 6 acceptance independent; use a deterministic fake adapter in isolated tests and the live endpoint only in local end-to-end verification. Stage 7 does not establish broader Stage 6 answer quality or production readiness.
