# Stage 7 - Human Approval Workflow

Status: **Done for the approved local synthetic scope; live Stage 6 workflow smoke deferred**
Pattern: Governed workflow with explicit human checkpoints
Builds on: Stage 4 bounded read-only claims agent; Stage 6 hybrid investigation

## 1. Goal

Make an investigation pause for an explicit human disposition, persist the workflow state, and resume only from a valid transition. An approval means permission to continue the workflow; it is not a coverage decision, claim approval, denial, payment authorization, or fraud determination.

Stage 6 was accepted on 2026-10-08 for the reviewed local synthetic scope. Stage 7 may call its live endpoint in local end-to-end verification and must use a deterministic fake for isolated tests and dependency-failure cases. Do not make Stage 7 acceptance imply broad Stage 6 answer quality or production readiness.

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
- Persist minimal audit history: workflow ID, state transition, disposition, timestamp, actor identifier, and references to investigation/trace IDs. Keep the request narrative only in the workflow payload while it can resume; clear it on completed, failed, or cancelled states. Persist a compact review result with summaries, findings, unresolved questions, source identifiers, bounded risk advice, and trace ID; strip full source facts and evidence text.
- Render pending review, resolved, failed, and unavailable states in the existing handler UI.
- Trace workflow creation, wait/resume, decision submission, and downstream service calls without claim narrative, PII, secrets, or full evidence.

## 4. Out of scope

- Real claims, customer information, or production authentication/security claims.
- Coverage decisions, fraud determinations, claim approval/denial, payments, or writes to claims systems.
- LLM-selected decisions or LLM control of workflow transitions.
- Specialist agents, broad Stage 6 answer-quality claims, or production deployment infrastructure.
- Automatic retries of provider-backed actions.

## 5. Accepted architecture

ADR-007 selects an explicit Postgres-backed state machine for this local synthetic prototype. The bounded comparison and its limits are recorded there. Use an isolated `workflows` schema and a separate least-privilege write role; do not use the read-only RAG role. The API worker claims each queued workflow once, records an in-progress state before calling Stage 6, and does not automatically retry. On startup, an in-progress operation left by the previous single API worker is marked failed rather than replayed.

The following scope decisions are settled for planning:

- Workflow creation is asynchronous. A worker invokes Stage 6 once; automatic retries are out of scope.
- `continue` moves the workflow to `completed`; `request_info` moves it to `needs_more_information` and requires an explicit human resume with a replacement narrative (5-1,000 characters); `stop` moves it to terminal `cancelled`.
- One synthetic reviewer is sufficient. No second reviewer, timeout, or escalation is included.
- A required `actor_id` is synthetic audit metadata only; it does not authenticate or authorize a person.
- Keep audit history minimal and retain it until local database teardown. Do not put narratives in audit records, API responses, logs, or telemetry. Keep the current narrative in the workflow request payload only until a terminal state; explicit resume replaces it with the bounded updated narrative. Clear it on completion, failure, or cancellation. The UI persists only the workflow UUID in local storage. Persist only the compact Stage 6 review projection; do not persist full source facts or evidence text.

## 6. Implementation slices after approval

1. Define typed workflow, state, disposition, and audit contracts, including idempotency behavior.
2. Implement the Postgres store, isolated credentials, and single background worker with a deterministic fake Stage 6 adapter for tests.
3. Add API operations for create, inspect/history, disposition, and explicit request-info resume; validate all transitions server-side.
4. Add handler UI for pending review, decision submission, request-info resume, history, and dependency failure.
5. Add unit/integration tests for process restart recovery, competing decisions, duplicate/stale requests, illegal transitions, Stage 6 failure, and no model-controlled state changes.
6. Add bounded OTEL spans and verify narratives/full evidence are excluded from audit and telemetry.
7. Deploy only to the local synthetic kind environment; update roadmap and handoff with measured results.

## 7. Acceptance criteria proposal

- Workflow state survives API/worker restart and resumes at the correct human wait point.
- Only the documented human disposition endpoint can advance a waiting workflow.
- Illegal, stale, duplicate, or out-of-order decisions do not advance state; repeated valid idempotency keys return the original result.
- Stage 6 dependency failure is represented distinctly and does not fabricate an investigation or risk result.
- Risk advisory remains separate from evidence and does not act as a human disposition.
- Audit history records transitions without claim narrative, PII, or full evidence.
- UI clearly presents unresolved questions and distinguishes workflow disposition from claim outcome.
- Unit/integration tests cover the state machine, persistence, API, and UI transitions; local rollout is verified.
- Use the live Stage 6 endpoint for local end-to-end verification and deterministic fakes for isolated tests. Stage 7 results do not imply broader Stage 6 answer quality or production readiness.

## 8. Closeout status (2026-10-09)

Verified locally:

- Force-replaced the API pod with a synthetic workflow in `investigating`. Startup recovery moved it to `failed` with `worker_interrupted`, incremented the version, cleared the request payload, and did not replay it. The synthetic probe and its audit row were removed after verification.
- A unique narrative canary was absent from API logs, workflow audit events, and OTEL collector output. The probe's payload was cleared at failure.
- The deployed frontend displayed the interrupted-workflow failure and no-retry message. Stage 7 store/API/worker tests passed (23 tests).
- Fixed workflow status serialization for Postgres UUID values. The API now returns HTTP 200 and a string workflow ID for persisted workflows; the deployed UI can load and display the failed state.

Deferred follow-up (not a Stage 8 dependency):

- One browser-submitted `CL-125` workflow reached `stage6_dependency_failed`. No automatic retry was made. The failure state and UI behavior were verified, but a successful frontend-to-live-Stage-6 workflow through human disposition remains unverified. No upstream exception detail was captured, so the dependency failure cause is undetermined.
- This live smoke is not a hard dependency for beginning Stage 8. Revisit it before claiming the full live workflow path is verified. If Stage 8 integrates specialist agents into the approval workflow, include that integration in Stage 8 acceptance checks.
