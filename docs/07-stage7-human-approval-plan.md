# Stage 7 - Human Approval Workflow

Status: **Draft for review; not approved; no implementation started**
Pattern: Governed workflow with explicit human checkpoints
Builds on: Stage 4 bounded read-only claims agent; Stage 6 hybrid investigation

## 1. Goal

Make an investigation pause for an explicit human disposition, persist the workflow state, and resume only from a valid transition. An approval means permission to continue the workflow; it is not a coverage decision, claim approval, denial, payment authorization, or fraud determination.

Stage 7 may begin with a deterministic fake Stage 6 adapter while Stage 6 remains open. Do not make Stage 7 acceptance depend on unverified Stage 6 answer quality. Connect the live Stage 6 endpoint only after its final JSON response path and flood schedule handling are verified.

## 2. Proposed user journey

1. A handler starts a workflow for a known synthetic claim.
2. The workflow obtains an investigation result and records its source IDs, evidence state, trace ID, and bounded risk advisory.
3. The workflow enters `awaiting_human_review` and presents the investigation and unresolved questions.
4. A human submits one allowed disposition. The workflow records actor, timestamp, and decision reason, then applies a documented transition.
5. The handler can inspect workflow status and history after refresh or service restart.

The meaning of each disposition is intentionally undecided pending user review. Do not equate a human task disposition with a claim or coverage outcome.

## 3. Scope proposal

- Create and inspect a persisted workflow for synthetic claim fixtures.
- Model explicit states such as `created`, `investigating`, `awaiting_human_review`, `needs_more_information`, `completed`, `failed`, and `cancelled`.
- Validate allowed state transitions server-side; model output cannot approve, reject, resume, or mutate a workflow.
- Make decision submission idempotent and reject duplicate or stale transitions safely.
- Persist a minimal audit history: workflow ID, state transition, disposition, timestamp, actor identifier, and references to investigation/trace IDs. Do not persist narratives or full evidence payloads unless separately approved.
- Render pending review, resolved, failed, and unavailable states in the existing handler UI.
- Trace workflow creation, wait/resume, decision submission, and downstream service calls without claim narrative, PII, secrets, or full evidence.

## 4. Out of scope

- Real claims, customer information, or production authentication/security claims.
- Coverage decisions, fraud determinations, claim approval/denial, payments, or writes to claims systems.
- LLM-selected decisions or LLM control of workflow transitions.
- Specialist agents, broad Stage 6 answer-quality claims, or production deployment infrastructure.
- Automatic retries of provider-backed actions.

## 5. Architecture decision required

ADR-007 is proposed but undecided. Compare at least:

| Option | Benefit | Cost / risk |
|---|---|---|
| Temporal workflow engine | Durable timers, waits, replay, and worker recovery | Additional local services and operational concepts; verify kind resource cost |
| Explicit database-backed state machine | Small visible Python implementation and fewer services | Must implement locking, recovery, timers, and idempotency carefully |
| In-process workflow | Lowest initial complexity | Not durable across pod restarts; unsuitable if restart-resume is an acceptance requirement |

Temporal is a candidate, not an approved decision. User review must settle engine, persistence, disposition semantics, identity/actor representation in the synthetic scope, timeout/escalation behavior, and whether workflow creation invokes Stage 6 synchronously or asynchronously.

## 6. Implementation slices after approval

1. Approve this plan and ADR-007 decision.
2. Define typed workflow, state, disposition, and audit contracts, including idempotency behavior.
3. Implement the selected durable workflow boundary and fake Stage 6 adapter.
4. Add API operations for create, inspect, and submit disposition; validate all transitions server-side.
5. Add handler UI for pending review, decision submission, history, and dependency failure.
6. Add unit/integration tests for restart recovery, duplicate/stale decisions, illegal transitions, Stage 6 failure/partial results, and no model-controlled state changes.
7. Add bounded OTEL spans and verify no narratives/full evidence enter telemetry.
8. Deploy only to the local synthetic kind environment after plan approval; update roadmap and handoff with measured results.

## 7. Acceptance criteria proposal

- Workflow state survives API/worker restart and resumes at the correct human wait point.
- Only the documented human disposition endpoint can advance a waiting workflow.
- Illegal, stale, duplicate, or out-of-order decisions do not advance state; repeated valid idempotency keys return the original result.
- Stage 6 dependency failure is represented distinctly and does not fabricate an investigation or risk result.
- Risk advisory remains separate from evidence and does not act as a human disposition.
- Audit history records transitions without claim narrative, PII, or full evidence.
- UI clearly presents unresolved questions and distinguishes workflow disposition from claim outcome.
- Unit/integration tests cover the state machine, persistence, API, and UI transitions; local rollout is verified.
- Stage 6 live integration remains gated on its outstanding answer/timeout checks; Stage 7 results do not imply Stage 6 acceptance.

## 8. Open questions for review

- Is Temporal required, or should a database-backed state machine be evaluated first?
- What are the exact human dispositions and what may each disposition authorize next?
- Is a second reviewer, escalation, timeout, or cancellation required?
- What synthetic actor identity is sufficient for local authorization tests?
- What minimal audit data and retention policy are acceptable?
- Should the initial approved prototype use a fake Stage 6 adapter until Stage 6 live verification closes?
