# Stage 4 - Claims Tool-Calling Workflow

Status: **APPROVED / DONE FOR LOCAL SYNTHETIC LEARNING SCOPE**
Pattern: Bounded tool orchestration
Builds on: Stage 2 RAG and Stage 3 Claims Copilot

## 0. Outcome

Build a human-reviewed, read-only claims investigation workflow that gathers synthetic claim-related facts through a bounded set of tools and returns a structured, traceable summary. It informs a handler; it does not decide coverage, approve or deny claims, issue payments, or persist handler decisions.

The Stage 2 Phase 2.4 `top_k=20` follow-up passed its documented exit checks on 2026-10-05; Stage 4 cluster integration is now unblocked.

## 1. Approved scope

- One modular internal `claims-service` exposing typed, read-only synthetic APIs for Claims, Policy, Customer, Payments, and Fraud.
- Plain-Python agent orchestration under `agents/claims/`, with explicit tool definitions, validation, limits, and REST adapters.
- LiteLLM tool/function calling for tool selection; all model traffic continues through LiteLLM.
- A separate `POST /v1/claims/agent-investigations` API contract; Stage 2/3 endpoints remain backward-compatible.
- Optional use of existing RAG for policy/procedure document evidence, distinct from facts returned by mock APIs.
- Structured output with validated source references, including mock-tool source IDs and RAG citations where present.
- Traces for agent, model, and tool steps without claim narratives, raw PII, or full tool payloads.
- API-focused delivery; no Stage 4 frontend changes.
- Synthetic data only; no authentication/authorization claim for real data or public exposure.

## 2. Out of scope

- Real claims/customer data or public ingress.
- Coverage determinations, approve/deny recommendations, payment actions, or any mutation tool.
- Claim, decision, or handler-feedback persistence.
- Temporal, multi-agent workflows, agent frameworks, or a standalone MCP server.
- Stage 4 frontend/UI work.
- Changes to Stage 2 retrieval semantics beyond independently closing the existing top_k=20 follow-up.

## 3. Approved architecture direction

- Keep the mock business domains in one deployable service, `apps/claims-service`, with separate resource endpoints and contracts.
- Keep the agent in a separate `agents/claims/` Python package. Use a visible, bounded orchestration loop with an allowlisted tool registry and typed adapters.
- Expose REST-backed internal tools to the model through LiteLLM's tool/function-call contract. Do not accept arbitrary URLs, SQL, tool names, or mutation requests from model output.
- Begin with configurable bounds of at most 6 tool calls over 4 model turns, bounded request/response sizes, and per-call timeouts. Changing those limits requires tests showing the need.
- Treat user narratives and tool results as untrusted data, not instructions. The final response must distinguish unsupported/missing evidence from dependency failure and must not claim a coverage outcome.
- Reuse the existing RAG service in-process where policy/procedure evidence is requested; do not call the API through its own HTTP endpoint.

## 4. Implementation slices

1. **Stage 2 prerequisite — complete (2026-10-05):** the top_k=20 bounded-generation follow-up passed unit and live verification before Stage 4 cluster integration. See the Stage 2 execution record.
2. **Contracts and fixtures:** define synthetic records, typed API schemas, tool argument/result schemas, final response schema, and scenario expectations. Policy facts from the mock Policy API remain distinct from policy wording retrieved by RAG.
3. **Mock service:** implement Claims, Policy, Customer, Payments, and Fraud read-only endpoints in one FastAPI service with deterministic synthetic fixtures, bounded inputs, predictable not-found behavior, and no persistence.
4. **Tool engine:** implement fixed tool registration, argument validation, REST execution, bounded model turns/calls, response validation, sanitized dependency failures, and explicit termination behavior.
5. **API integration:** add a separate endpoint to `ai-api`, preserve existing contracts, validate final model output and all references, and return a bounded structured summary plus source metadata.
6. **Tracing/security:** trace the agent run, LiteLLM tool selection, each tool invocation, and each RAG step. Record bounded operational metadata only. Do not record claim narrative, raw PII, secrets, or full tool/evidence payloads.
7. **Tests/evaluation:** add unit tests with fake LiteLLM/tool adapters, integration tests against the service, and a fixed synthetic scenario suite. Report tool selection, required-fact coverage, unsupported assertion rate, failure handling, prohibited-action rate, latency, and dependency failures. Required prohibited-action rate: zero.
8. **Deployment:** add a pinned, hardened claims-service image and internal Kubernetes Deployment/Service; register resources in Kustomize. Add a build/load script following existing Podman-aware conventions.
9. **Verification/docs:** run unit/integration/scenario tests, Python compile checks, shell syntax, Kustomize render, image build/load and rollout checks. Run one controlled provider-backed smoke request without automatic retries and correlate its trace. Update README, roadmap, and AGENTS status/runbooks with actual results.

## 5. Contracts and safety requirements

- The tool registry is the sole authority for tools callable by the model. Unknown tools and malformed arguments fail closed.
- Tool arguments are constrained to known synthetic identifiers and explicitly supported filters. Never provide shell, SQL, arbitrary HTTP, or generic key/value execution tools.
- All current tools are read-only. A requested mutation, coverage decision, payment, or approval action is rejected and counted as a prohibited action in evaluation.
- Bound model turns, tool calls, tool timeouts, argument lengths, tool response size, and final output size. No automatic retries for provider-backed operations unless separately approved.
- Tool and model failures are not `insufficient_evidence`; they produce sanitized dependency errors. Missing records/evidence are represented distinctly from infrastructure failures.
- Every factual final assertion must point to one or more returned tool sources or validated RAG citations. Referential checks do not prove semantic entailment; evaluation must state this limitation.
- Narratives and tool responses are untrusted input. The system prompt and tool implementation must prevent tool output from expanding permissions or changing tool definitions.
- Use synthetic information only. Local unauthenticated service boundaries do not constitute production security controls.

## 6. Proposed ADRs

- ADR-005, **Proposed**: plain Python bounded tool loop versus an agent framework.
- ADR-006, **Proposed**: REST-backed tool adapter versus a standalone MCP server.
- Recommendations follow this plan; the user approves the decisions before the ADRs become Accepted.

## 7. Acceptance criteria

- Five domains are represented by typed, tested, read-only mock APIs in one internal service.
- The agent invokes only allowlisted tools and stays within tested execution limits.
- Unknown tools, invalid arguments, prohibited actions, malformed model responses, timeouts, and service errors fail safely.
- The new API returns a validated, bounded, source-linked investigation summary and never recommends or performs claim decisions/actions.
- Claim narratives, secrets, raw PII, and full tool/evidence payloads do not appear in logs or spans.
- Existing Stage 2/3 APIs remain compatible.
- Scenario tests account for expected tool use, required facts, unsupported assertions, and failures; prohibited-action rate is zero.
- Kubernetes manifests render; hardened internal service deploys; one controlled live request has a collector-correlated trace.
- Documentation reports measured results and limitations without claiming real-data readiness or semantic faithfulness.

## 8. Verification commands

```bash
python3 -m pytest -q tests/unit
python3 -m pytest -q tests/integration
python3 -m py_compile apps/ai-api/main.py apps/claims-service/main.py agents/claims/*.py
bash -n scripts/*.sh
kubectl kustomize infrastructure/kubernetes/base >/dev/null
git diff --check
```

## 9. Decisions / execution record

- Approved by user: one modular mock service; read-only fraud facts without scoring/recommendations; REST-backed tools via LiteLLM; API-only scope; close Stage 2 follow-up before Stage 4 cluster integration.
- Stage 2 top_k=20 prerequisite: passed 2026-10-05; the API was rebuilt and rolled out, and the live hybrid top_k=20 request returned a cited answer with a collector-correlated trace. Stage 4 cluster integration is unblocked.
- Stage 4 verification (2026-10-06): `263 passed, 2 skipped` across unit and integration tests; the claims package reports 85% coverage under the focused test set. Python compile, shell syntax, Kustomize render, and `git diff --check` pass. The hardened `claims-service` image (`localhost/claims-service:stage4.0`) and API are both 1/1 ready in `ai-stage1`; Kustomize includes the service.
- Stage 4 live smoke (2026-10-05): one bounded provider-backed request returned `answered` using the `claim` and `fraud_signal` sources, 2 tool calls, valid source references, and trace `6f35cdc40fb690886799ed6791a26b15`; collector inspection confirmed API, agent, model, and tool spans and no raw narrative in the collected trace. A separate broad request safely stopped at the four-turn bound before final output; see [the evaluation report](eval/stage4-claims-agent-report.md). No automatic retries were used.
- Evaluation reports exact-source checks and zero prohibited tool dispatch in the deterministic suite. Semantic entailment, broad scenario quality, live RAG evidence selection, and real-data security remain unmeasured; Stage 4 remains in progress pending broader evaluation and review.
- 2026-10-06 addendum (supersedes the dated Stage 4 verification/evaluation bullets above): 263 unit/integration tests pass, 2 skip, and focused claims coverage is 85%. Live RAG evidence was exercised; one pipe-repair finding exactly matched its cited synthetic policy sentence. Latest trace `e188a3b16bad10581ec8711bf33607f1` has 2 tool calls, 6 sources, and agent/model/tool/RAG spans without an agent exception. The user reviewed and accepted the fixed scenario results. Stage 4 is Done for the local synthetic scope; the saved all-domains case omitted payment/fraud sources, and the small sample is not evidence of production readiness. See [the current evaluation report](eval/stage4-claims-agent-report.md).