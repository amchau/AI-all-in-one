# ADR-007 - Stage 7 Workflow Engine

## Status

Proposed; decision pending user review. No workflow engine has been selected.

## Context

Stage 7 adds a durable human approval checkpoint to the synthetic claims investigation workflow. The workflow must wait for a human, survive service/worker restarts, validate state transitions, and avoid treating a disposition as a claim or coverage decision. Stage 6 remains open: the flood-extension answer path and the deployed final JSON timeout have not both passed live verification. Stage 7 can be prototyped against a deterministic fake Stage 6 adapter while those gaps remain open.

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

Deferred. Temporal is a candidate, not the selected engine. The user must review trade-offs and the Stage 7 plan before implementation.

## Validation

After a decision, test wait/resume across worker/API restarts, idempotent and stale decisions, illegal state transitions, timeout/cancellation semantics, and Stage 6 dependency failure. Measure local resource footprint and document operational steps. Do not use a real claim or imply production readiness.

## Consequences

- No Stage 7 implementation should begin until this ADR and the Stage 7 plan are approved.
- Preserve claim-decision authority with the human and keep model outputs outside workflow control.
- Keep Stage 6 acceptance independent; use a deterministic fake adapter until the Stage 6 live gates pass.
