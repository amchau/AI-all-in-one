# Stage 4 Claims Agent: Evaluation and Deployment Report

Date: 2026-10-06  
Status: implementation and local integration verified; Stage 4 evaluation remains in progress.

## Scope and method

The checks exercise two fixed synthetic claims, the agent tool loop, API boundary, RAG evidence
adapter, and local Kubernetes deployment. Model output in automated scenarios is stubbed through the
LiteLLM-compatible HTTP boundary; these tests verify dispatch, record handling, source-reference
enforcement, and failure behavior, not model reasoning quality. No real claims or customer data were
used.

## Results

| Measure | Result | Interpretation |
|---|---:|---|
| Unit and integration suite | 252 passed, 2 skipped | `tests/unit` plus `tests/integration`; 23 dependency deprecation warnings. |
| `agents.claims` test coverage | 80% | Focused claims suite: 24 tests across agent, API, service, and integration modules. |
| Read-only domain tool coverage | 5/5 | Claim, policy, customer, payment, and fraud lookups were driven through the actual synthetic service with scripted model calls. Each result was returned with its expected source ID. This is not a model tool-selection accuracy score. |
| Unit and integration suite | 263 passed, 2 skipped | `tests/unit` plus `tests/integration`; 23 dependency deprecation warnings. |
| `agents.claims` test coverage | 85% | Focused claims suite: 35 tests across agent, API, service, and integration modules. |
| Synthetic fixture coverage | 2 claims | HOME-002 claim `CL-123` and COMM-001 claim `CL-124` exercise independent claim/policy/customer bindings. |
| Read-only domain tool coverage | 5/5 | Claim, policy, customer, payment, and fraud lookups were driven through the actual synthetic service with scripted model calls. Each result was returned with its expected source ID. This is not a model tool-selection accuracy score. |
| Unsupported source assertions | 0 accepted / 1 attempted | A fabricated source ID was rejected. Referential validation does not establish that cited text semantically supports the assertion. |
| Prohibited action dispatch | 0/4 (0%) | `run_sql`, `approve_claim`, `issue_payment`, and `update_claim` requests were rejected before any business-service call. This is an execution rate, not a measure of how often a model might attempt such a request in production. |
| Injected model dependency failure | 1/1 safely surfaced; no retry | An HTTP 503 from the LiteLLM boundary produced the agent dependency error. The API boundary has a separate sanitized-error test. |
| Successful provider-backed claims smoke | 1 request, 2 tool calls, 1,729 ms | Returned `answered`, claim and fraud-signal sources, and source references present in the response. One sample is not a reliability or latency distribution. |
| Successful provider-backed RAG smoke | 1 exact-evidence response; 2 tool calls; 6,974 ms | Returned five policy-evidence sources. The pipe-repair finding exactly matched the cited synthetic policy sentence; all references resolved. Response trace ID: `a39a56ae75a120ed83fb579c7ce2d1f3`. |
| Latest final-function live trace | 2 tool calls, 6 sources | Trace `e188a3b16bad10581ec8711bf33607f1` has agent/model/tool spans plus RAG source-resolution, embed, sparse-embed, search, rerank, and generation spans; no agent exception was recorded. |
| Observed live failures | Several bounded failures during iteration | Earlier probes exposed model tool-order violations, Groq JSON/function-call incompatibility, and premature free-form output. These were addressed with claim-first tool exposure, forced final-answer function calling, and validated early structured output. No automatic retries were used. |
| Trace and narrative handling | Correlated and checked | Successful response trace `6f35cdc40fb690886799ed6791a26b15` includes API, agent, model, and tool spans. Collector inspection did not find the request narrative in trace output. |
| Deployment | API 1/1; claims-service 1/1 ready | `localhost/ai-api:stage4.0` and `localhost/claims-service:stage4.0` are running in `ai-stage1`; service resource renders through Kustomize. |

Live requests used the LiteLLM model alias `gpt-oss-20b`, synthetic data, and no automatic retries.
These samples validate integration and a single exact-evidence statement; they do not establish
reliable model tool selection, broad required-fact coverage, or a distributional unsupported-assertion
rate.

## Verification commands

```bash
./.venv/bin/python -m pytest -q tests/unit tests/integration
./.venv/bin/python -m pytest -q tests/unit/test_claims_agent.py tests/unit/test_claims_agent_api.py tests/unit/test_claims_service.py tests/integration/test_claims_agent_service.py --cov=agents.claims --cov-report=term-missing
./.venv/bin/python -m py_compile apps/ai-api/main.py apps/claims-service/main.py agents/claims/*.py
bash -n scripts/*.sh
kubectl kustomize infrastructure/kubernetes/base >/dev/null
git diff --check
```

## Limitations and next work

- Scripted selections do not measure autonomous tool-selection quality. Provider-backed samples are
  too few to estimate reliability, required-fact coverage, or p95 latency.
- Source-ID checks reject unknown references but do not prove semantic entailment, factual
  completeness, or appropriate uncertainty. One exact quoted finding was reviewed against its
  source, but no multi-case human quality labels were collected.
- Live RAG evidence retrieval has been exercised. The RAG adapter's policy binding and temporal
  inputs also have unit coverage; broader live cases across policies and dates remain unmeasured.
- Deployment is a local unauthenticated synthetic-data setup, not a production security review. No
  real-data readiness, business decision authority, or semantic faithfulness is claimed.

Stage 4 implementation and local deployment acceptance checks pass. Keep the roadmap status in
progress until a reviewer evaluates a fixed, multi-case provider-backed scenario set for expected
tool selection, required-fact coverage, unsupported assertions, and prohibited-action attempts. Do
not claim production readiness or general semantic faithfulness from this learning-stage evaluation.
