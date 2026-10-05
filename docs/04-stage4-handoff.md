# Stage 4 handoff: claims tool-calling workflow

Updated: 2026-10-05  
Status: **local integration deployed; evaluation and review remain in progress**

This is a session handoff, not a change in the approved Stage 4 scope. The canonical implementation
plan is [04-stage4-tool-calling-agent-plan.md](04-stage4-tool-calling-agent-plan.md); measured
results and limitations are in the [Stage 4 evaluation report](eval/stage4-claims-agent-report.md).
Continue to use synthetic data only. Do not add write tools, coverage decisions, approvals, payment
actions, new services, or production claims without an approved plan amendment.

## Actions completed

- Implemented a deterministic, read-only synthetic Claims service for claim, policy, customer,
payment, and fraud-signal records.
- Implemented the plain-Python `agents/claims` tool loop and the separate
`POST /v1/claims/agent-investigations` API route. The loop uses an allowlist, validates arguments and
source IDs, and is bounded at six tool calls over four model turns. LiteLLM remains the only model
boundary; policy evidence is optional through the existing RAG path.
- Added unit/API/integration tests, including each of the five synthetic domain lookups, invalid or
prohibited tool rejection, invalid source rejection, bounds, and sanitized dependency failure tests.
- Built and loaded `localhost/claims-service:stage4.0`, registered its hardened internal Deployment
and ClusterIP Service in Kustomize, and deployed it in `ai-platform`. At the last verification,
`ai-api` and `claims-service` were both 1/1 ready in cluster `ai-stage1`.
- Ran the unit and integration suites: **252 passed, 2 skipped**. The focused claims test set reports
**80% coverage**. Python compilation, shell syntax, Kustomize rendering, and `git diff --check`
passed.
- Sent one bounded provider-backed request without automatic retries. It returned an answered brief
using claim and fraud-signal sources, with two tool calls and resolvable source references. Trace
`6f35cdc40fb690886799ed6791a26b15` was found in the collector with API, agent, model, and tool spans;
the raw request narrative was not found in collector output.
- Recorded a separate broad provider-backed request that exhausted the four-turn budget before a
final response. It failed closed with a sanitized 502. This is an observed limitation, not a passed
answer-quality scenario.
- The deterministic suite rejected all four prohibited tool names before any business-service call
and rejected one fabricated source ID. These results verify safety behavior under scripted model
responses; they do not measure how often a real model will make unsafe requests.

Full metrics, test commands, and evaluation limitations are recorded in the [evaluation report](eval/stage4-claims-agent-report.md).

## Next steps, in order

1. **Inspect the current worktree and local cluster.** Start with `git status --short`, review this
   handoff and the Stage 4 plan, then check `kubectl --context kind-ai-stage1 -n ai-platform get
deploy ai-api claims-service` and rollout status before assuming the local cluster is still present.
2. **Address the observed turn-budget failure without relaxing the approved bounds.** Review the
   system prompt and loop behavior so the model is more likely to finish after its tool calls while
   retaining the maximum of four model turns and six tool calls. Add deterministic tests for the
   turn sequence and failure contract. Do not increase the configured bounds without user approval
   and evidence that the change is needed.
3. **Broaden fixed synthetic scenarios.** Add multiple claim fixtures and test answerable,
   insufficient-evidence, missing/conflicting records, tool/dependency failures, malformed outputs,
   oversized responses, and adversarial instructions in both narratives and tool-returned text.
   Keep all mutation and prohibited-action cases fail-closed.
4. **Exercise optional RAG policy evidence once through a controlled integration scenario.** Verify
   the claim-to-policy binding, loss-date inputs, source IDs/citations, bounded returned evidence,
   and trace spans. Use synthetic data and no automatic retries.
5. **Measure model behavior separately from orchestration tests.** With a documented fixed scenario
   set, report model tool-selection accuracy, required-fact coverage, unsupported assertion rate,
   prohibited-action attempts and dispatches, failure handling, latency, and dependency failures.
   Use semantic review or human labels for entailment; source-ID validity alone is insufficient.
6. **Re-run acceptance checks and update artifacts.** Run unit/integration and focused coverage tests,
   compile/shell/Kustomize/diff checks, verify deployments, then perform only the planned controlled
   provider-backed smoke and trace correlation. Update the evaluation report and plan with actual
   results; keep Stage 4 in progress until the plan's acceptance criteria and limitations are
   explicitly reviewed.

## Useful checks

- Full tests: `./.venv/bin/python -m pytest -q tests/unit tests/integration`
- Focused coverage: `./.venv/bin/python -m pytest -q tests/unit/test_claims_agent.py tests/unit/test_claims_agent_api.py tests/unit/test_claims_service.py tests/integration/test_claims_agent_service.py --cov=agents.claims --cov-report=term-missing`
- Static and manifest checks: `./.venv/bin/python -m py_compile apps/ai-api/main.py apps/claims-service/main.py agents/claims/*.py`, `bash -n scripts/*.sh`, `kubectl kustomize infrastructure/kubernetes/base >/dev/null`, and `git diff --check`
- Rebuild/reload the service if necessary: `./scripts/build-claims-service.sh`; apply `infrastructure/kubernetes/base/claims-service.yaml` and wait for `deploy/claims-service` rollout.
- API endpoint: `POST /v1/claims/agent-investigations` through the existing local API port-forward. A provider-backed request can incur external model usage; send synthetic text only and never add automatic retries.
