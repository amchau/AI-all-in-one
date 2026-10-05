# Stage 4 Claims Agent: Evaluation and Deployment Report

Date: 2026-10-05  
Status: local synthetic integration verified; Stage 4 remains in progress.

## Scope and method

The checks exercise the fixed synthetic claims fixture, agent tool loop, API boundary, and local
Kubernetes deployment. Model output in automated scenarios is stubbed through the LiteLLM-compatible
HTTP boundary; these tests verify dispatch, record handling, source-reference enforcement, and failure
behavior, not model reasoning quality. No real claims or customer data were used.

## Results

| Measure | Result | Interpretation |
|---|---:|---|
| Unit and integration suite | 252 passed, 2 skipped | `tests/unit` plus `tests/integration`; 23 dependency deprecation warnings. |
| `agents.claims` test coverage | 80% | Focused claims suite: 24 tests across agent, API, service, and integration modules. |
| Read-only domain tool coverage | 5/5 | Claim, policy, customer, payment, and fraud lookups were driven through the actual synthetic service with scripted model calls. Each result was returned with its expected source ID. This is not a model tool-selection accuracy score. |
| Unsupported source assertions | 0 accepted / 1 attempted | A fabricated source ID was rejected. Referential validation does not establish that cited text semantically supports the assertion. |
| Prohibited action dispatch | 0/4 (0%) | `run_sql`, `approve_claim`, `issue_payment`, and `update_claim` requests were rejected before any business-service call. This is an execution rate, not a measure of how often a model might attempt such a request in production. |
| Injected model dependency failure | 1/1 safely surfaced; no retry | An HTTP 503 from the LiteLLM boundary produced the agent dependency error. The API boundary has a separate sanitized-error test. |
| Successful provider-backed smoke | 1 request, 2 tool calls, 1,729 ms | Returned `answered`, claim and fraud-signal sources, and only source references present in the response. One successful sample is not a latency distribution. |
| Broad provider-backed request | 1 request stopped at the 4-turn limit | The model used all four turns on tool calls and did not return a final payload. The agent failed closed with HTTP 502; no mutation was available or dispatched. This bounded failure is recorded rather than hidden. |
| Trace and narrative handling | Correlated and checked | Successful response trace `6f35cdc40fb690886799ed6791a26b15` includes API, agent, model, and tool spans. Collector inspection did not find the request narrative in trace output. |
| Deployment | API 1/1; claims-service 1/1 ready | `localhost/ai-api:stage4.0` and `localhost/claims-service:stage4.0` are running in `ai-stage1`; service resource renders through Kustomize. |

The live smoke used the LiteLLM model alias `gpt-oss-20b`. Each provider-backed request was sent once
without automatic retries. The successful sample intentionally exercised claim and fraud facts; live
policy-evidence retrieval through RAG was not exercised.

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

- The synthetic service has one claim fixture; five domain-tool checks establish contract wiring, not
  breadth across claim types or distributional performance.
- Scripted model selections do not measure autonomous tool-selection quality. One successful live
  request and one bounded live failure are too few to estimate reliability or p95 latency.
- Source-ID checks reject unknown references but do not prove semantic entailment, factual
  completeness, or appropriate uncertainty. No human quality labels were collected.
- The optional policy-evidence tool and live RAG path need a separate controlled scenario. The RAG
  adapter's policy binding and temporal inputs have unit coverage only.
- Deployment is a local unauthenticated synthetic-data setup, not a production security review. No
  real-data readiness, business decision authority, or semantic faithfulness is claimed.

Stage 4 stays in progress until broader scenario evaluation and review close these limitations.
