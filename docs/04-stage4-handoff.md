# Stage 4 handoff: claims tool-calling workflow

Updated: 2026-10-06  
Status: **implementation and local integration complete; model-quality review remains in progress**

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
- Ran the unit and integration suites: **263 passed, 2 skipped**. The focused claims test set reports
**85% coverage**. Python compilation, shell syntax, Kustomize rendering, and `git diff --check`
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
- Added a second synthetic claim/policy/customer fixture and response identity checks. `get_claim` is
the only initial tool; linked tools appear only after its response is validated. The final turn uses
a forced `submit_final_answer` function; valid structured output returned earlier is still locally
validated and accepted.
- Exercised live RAG policy evidence. One finding exactly matched its cited synthetic policy sentence.
The latest trace `e188a3b16bad10581ec8711bf33607f1` recorded 2 tool calls, 6 sources, and agent,
model, tool, and RAG spans without an agent exception.

Full metrics, test commands, and evaluation limitations are recorded in the [evaluation report](eval/stage4-claims-agent-report.md).

## Remaining closeout

1. Have a reviewer assess the fixed provider-backed scenarios for tool choice, required-fact coverage,
   unsupported assertions, and uncertainty. The implementation, deterministic safety scenarios, live
   RAG path, trace checks, and deployment gates are complete.
2. Keep Stage 4 in progress until that review accepts the documented model-quality limitations. Do
   not claim production readiness or broad semantic faithfulness from the current small sample.

## Useful checks

- Full tests: `./.venv/bin/python -m pytest -q tests/unit tests/integration`
- Focused coverage: `./.venv/bin/python -m pytest -q tests/unit/test_claims_agent.py tests/unit/test_claims_agent_api.py tests/unit/test_claims_service.py tests/integration/test_claims_agent_service.py --cov=agents.claims --cov-report=term-missing`
- Static and manifest checks: `./.venv/bin/python -m py_compile apps/ai-api/main.py apps/claims-service/main.py agents/claims/*.py`, `bash -n scripts/*.sh`, `kubectl kustomize infrastructure/kubernetes/base >/dev/null`, and `git diff --check`
- Rebuild/reload the service if necessary: `./scripts/build-claims-service.sh`; apply `infrastructure/kubernetes/base/claims-service.yaml` and wait for `deploy/claims-service` rollout.
- API endpoint: `POST /v1/claims/agent-investigations` through the existing local API port-forward. A provider-backed request can incur external model usage; send synthetic text only and never add automatic retries.
