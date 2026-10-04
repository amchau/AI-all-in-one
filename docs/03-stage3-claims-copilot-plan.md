# Stage 3 - Claims Copilot

Status: **IN PROGRESS**
Pattern: Human-in-the-loop investigation
Builds on: Stage 2 RAG; Stage 2 remains **IN PROGRESS**, including the open Phase 2.4 `top_k=20` generation follow-up.

## 0. Outcome

Give a claims handler a local interface to submit synthetic claim context and inspect a
structured evidence brief grounded in the existing policy corpus. The copilot informs the
handler; it does not decide coverage or recommend approve/deny outcomes.

## 1. Approved scope

- Separate React + Vite frontend, deployed alongside `ai-api` in the existing local kind cluster.
- Handler-entered claim ID, policy ID, loss date, and narrative. Guidance date defaults to loss date.
- One investigation request uses fixed `hybrid_rerank`, `top_k=5` and the existing date-aware
  source selection, citation validation, abstention, and tracing behavior.
- Structured result: summary, evidence-backed findings with citations, evidence status, and
  unresolved questions. Every factual finding must cite retrieved evidence.
- The handler can inspect cited source metadata and retrieved excerpts. Insufficient evidence,
  validation failures, and dependency errors are distinct states.
- Synthetic, local-only data. Claim narrative is sent to hosted providers through LiteLLM
  (currently Groq for generation and OpenRouter for embeddings). Never submit real PII. No claim
  persistence, decision capture, or auth.
- Same-origin frontend `/api` proxy to the cluster-internal API.

## 2. Out of scope

- Stage 2 completion or the Phase 2.4 `top_k=20` follow-up.
- Document upload or ingestion lifecycle (deferred separately despite Stage 2 D8).
- Coverage determinations, approve/deny recommendations, or automated claim actions.
- Claim/policy/customer APIs and tool-calling (Stage 4), persisted approval workflows (Stage 7),
  multi-agent workflows, or real-data authentication/authorization.
- Claim history, handler decision/feedback persistence, or new telemetry backends.
- Replacing or removing the legacy `/v1/investigate` endpoint; it remains cluster-internal and is
  not used by the Claims Copilot UI.

## 3. Implementation slices

1. Define a bounded API contract for claim context and the structured evidence brief. Preserve
   citation references as validated data; do not parse flattened answer prose. Keep
   `/v1/rag/query` backward-compatible and fix retrieval mode and `top_k` server-side.
2. Add unit/API tests for input bounds, policy/date selection, grounded findings, citation mapping,
   abstention, sanitized errors, trace propagation, and existing RAG contract compatibility.
3. Build the React/Vite form and evidence-review experience with validation, loading, answered,
   insufficient-evidence, and dependency-error states. Show source title, section/clause/page,
   and cited excerpt; provide citation navigation. Do not add decision controls or history.
4. Package the frontend with a pinned multi-stage image, same-origin Nginx `/api` proxy, hardened
   Deployment/Service, Kustomize registration, and a narrow local build/port-forward workflow.
5. Verify component and Playwright flows with a mocked API, then deploy locally and run one
   known-answerable HOME-002 investigation at `top_k=5`. Correlate its trace ID with collector
   output without automatically retrying the model-backed request.
6. Update README, roadmap, and AGENTS status/runbooks to reflect Stage 3 progress while keeping
   Stage 2 in progress and the Phase 2.4 follow-up open.

## 4. Acceptance criteria

- The investigation request rejects invalid or oversized claim fields and cannot override the
  fixed retrieval mode or `top_k=5`.
- Every returned finding has one or more refs that resolve to returned citations and retrieved
  chunks. Unsupported findings are rejected or converted to insufficient evidence.
- Abstention returns no factual findings; missing evidence is never rendered as an answer.
- Dependency failures return generic client-safe errors. Claim narrative and other claim content
  are not recorded in logs or span attributes.
- `/v1/rag/query` retains its existing request/response behavior.
- Frontend supports validation, loading, answered, insufficient-evidence, and dependency-error
  states; cited evidence can be inspected on desktop and mobile without layout overflow.
- Kustomize renders; frontend/API images build and load locally; hardened frontend resources roll
  out; a live trace is visible in the collector.
- Documentation does not mark Stage 2 complete or close the Phase 2.4 `top_k=20` follow-up.

## 5. Verification

- `python3 -m pytest -q tests/unit`
- Frontend install/build/typecheck/component tests and Playwright E2E for the response states above.
- `kubectl kustomize infrastructure/kubernetes/base >/dev/null`
- `bash -n` for touched scripts; local image build/load and rollout checks.
- One live, known-answerable HOME-002 request with citation verification and API-to-collector
  trace correlation. Do not automatically repeat provider-backed requests.
- `git diff --check`

## 6. Known limitations

Stage 2.5 mode metrics are comparative and do not prove semantic faithfulness. The selected
`hybrid_rerank` mode is the MVP default because it had the highest measured recall@5 in the
35-case comparison; it is not a coverage decision. The API and UI are for synthetic local-lab use
only, without authentication or real-data controls.

## 7. Execution record (2026-10-04)

- Added the structured investigation API and local React/Vite UI; deployed only the frontend and
  updated `ai-api` workloads to `kind-ai-stage1`.
- Backend unit suite: 224 passed. Frontend: 12 tests passed with 98.6% line coverage; 6 Playwright
  runs passed across desktop and mobile Chromium, including dev proxy allowlisting. Production build, Kustomize render, Nginx config,
  and touched shell syntax checks passed.
- Frontend health, same-origin API proxy, and API dependency health checks passed.
- One corrected live investigation attempt at fixed `hybrid_rerank`, `top_k=5` returned HTTP 502.
  LiteLLM reported Groq `json_validate_failed`; retrieval and reranking spans completed, and the
  `rag.generate` failure was exported. No automatic or follow-up model request was made.
- Stage 3 remains in progress pending a successful live generated brief. Stage 2 and the Phase 2.4
  `top_k=20` follow-up remain open; resolving the provider JSON failure is not folded into this stage.