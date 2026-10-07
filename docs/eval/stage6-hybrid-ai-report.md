# Stage 6 Hybrid Claims Investigation: Integration Report

Date: 2026-10-06
Status: Mandatory-retrieval amendment deployed and live-trace verified 2026-10-07. Synthetic scope
only; pending user review.

## Scope

This report covers the Stage 6 combined API, fixture-owned risk feature boundary, existing handler
UI, local Kubernetes rollout, automated tests, and one provider-backed smoke request. It does not
evaluate real-world risk quality, broad agent reliability, or production readiness. The smoke is a
single scenario and did not retrieve RAG policy evidence.

## Verification results

| Check | Result | Interpretation |
|---|---:|---|
| Python 3.12 backend unit/integration suite | 307 passed, 2 skipped | Includes Stage 6 adapter, feature service, combined API, and existing regressions. One existing Starlette deprecation warning. |
| Focused claims/agent coverage | 87% total | `agents.claims.models.py` 94%, `agents.claims.risk.py` 95%, `agents.claims.runner.py` 83%. |
| Frontend component/API/validation tests | 14 passed; 98.76% line coverage | Includes distinct risk advice, unavailable-risk partial response, request validation, and source evidence. |
| Desktop/mobile Playwright suite | 6 passed | Combined workflow, blocked old/unrelated proxy routes, abstention/error states, no horizontal overflow. |
| Frontend production build | Passed | TypeScript and Vite build succeeded. Vite emitted two dependency-comment warnings from Zod/Rollup. |
| Python compile, shell syntax, Kustomize, diff check | Passed | Compile covered API, claims service, agent modules, and touched tests. |
| Local images | Built and loaded | `localhost/claims-service:stage6.0` and `localhost/ai-api:stage6.0`. |
| Local rollout | Passed | `claims-service` and `ai-api` successfully rolled out in `kind-ai-stage1`. |

## Live smoke

One synthetic request to `POST /v1/claims/hybrid-investigations` returned HTTP 200 in 2,778 ms.
The claims service resolved policy `HOME-002` and loss date `2025-03-01`; the requested guidance
date `2026-01-01` was preserved. The agent made three bounded tool calls and returned claim, policy,
and customer sources. Stage 5 returned `routine_review`, no handler triage, and model version
`stage5-cfb12f6a9cc1`. The response contained no probability. No automatic retry was used.

Trace `cdf96f1cf435bfee28cfbd7278b5bec5` was found in the collector. It includes
`claims.hybrid_investigation` and `claims.risk_advisory`; the risk span records outcome, model
version, and 13 ms latency. The observed Stage 6 spans contain no raw risk feature values or labels.
The API log entries showed successful feature lookup and risk inference and did not contain the
claim narrative.

This model-selected investigation did not call the optional RAG evidence tool. It produced no policy
evidence citations. This verifies the agent-plus-risk path and trace correlation only; it does not
prove end-to-end Stage 6 RAG retrieval or evidence quality. Existing Stage 4 live RAG verification
and Stage 6 guidance-date/unit tests remain separate evidence for that path. Do not send a second
provider-backed request without an approved scenario.

## Limitations

- Claims, feature values, policy records, and customer data are synthetic. Stage 5 labels are
  rule-derived referral indicators, not fraud ground truth.
- The Stage 5 routine/priority output is advisory. It does not establish a claim outcome.
- One smoke request is not a latency or reliability distribution.
- The smoke did not exercise live RAG retrieval; current agent behavior may omit optional tools, as
  this response omitted payment/fraud domains too. Stage 4's saved all-domain evaluation already
  documents incomplete source coverage.
- The deployment is local, unauthenticated, and unsuitable for real claims data.

## Mandatory-Retrieval Amendment (2026-10-07)

The user selected deterministic retrieval before the agent for every combined investigation. The
implementation now runs `hybrid_rerank` in retrieval-only mode, passes validated source-linked
chunks into the agent's initial context, and reports `retrieved`, `insufficient_evidence`, or
`unavailable` separately. It does not call the RAG answer generator; the agent makes the final brief.

## Review of the 2026-10-07 Smoke Response

The user-provided response passes the orchestration/source-integrity checks: it reports
`policy_evidence_status=retrieved`; all summary and finding source IDs resolve to one of the eight
returned sources (five policy-evidence chunks plus claim, policy, and customer records); and the
collector trace confirms retrieval, reranking, agent, and risk spans. This verifies that retrieval
ran and cited sources were returned. It does not establish complete or correct evidence coverage.

Answer-quality findings:

- **Relevant endorsement coverage is incomplete.** The returned policy sources include base clauses
  3 and 4.2, but omit the HOME-002 water clarification endorsement and flood extension, both present
  in the corpus and effective before the 2025-03-01 loss date. The water clarification is directly
  relevant to the sudden-escape versus gradual-leak distinction. The flood extension would alter
  base clause 4.2 only if listed on the policy schedule; the synthetic claim fixture has no schedule
  data, so applicability must remain unresolved rather than assumed.
- **The summary's "within the policy period" statement is stronger than the available contract
  data.** The retrieved sources establish an effective date and the claim's loss date, but the policy
  registry does not represent an expiry date. Phrase this as “after the recorded effective date” or
  leave policy-in-force confirmation unresolved.
- **Unresolved questions are empty despite missing schedule and cause evidence.** The returned
  procedure source asks handlers to establish the cause and obtain proportionate evidence. The brief
  should leave schedule/endorsement applicability and cause/duration questions open when no supporting
  source answers them.

Acceptance comparison: mandatory retrieval, trace correlation, and citation-to-returned-source
integrity pass. Retrieval coverage and answer completeness are partial for this scenario. Do not mark
Stage 6 answer-quality acceptance complete from this single response. Follow-up should add a fixed
combined-workflow case for a pipe-failure narrative, assert retrieval of the applicable water
clarification evidence or explicit uncertainty, and verify that absent schedule data is not turned
into an endorsement-presence/absence claim. No additional provider-backed request is implied by this
review.
Post-amendment checks: **315 backend tests passed, 2 skipped**; focused agent/RAG coverage is **87%**;
frontend **15 tests passed**, **98.8% line coverage**, production build passed, and **6 Playwright
desktop/mobile tests passed**. Route tests cover retrieval-before-agent, source injection, and
partial agent responses on retrieval failure. Python compilation, shell syntax, Kustomize render, and
`git diff --check` passed.

An initial redeployment attempt could not reach the kind API server at `10.129.24.10:443`; access
later recovered. On 2026-10-07, the user reported a combined response with
`policy_evidence_status=retrieved` and trace `0826761b079e1dfc1e0de72aadca0b8d`. Collector
inspection confirmed `rag.source_resolution`, `rag.embed`, `rag.sparse_embed`, `rag.search`, and
`rag.rerank` spans; reranking processed 20 candidates and returned 20 results. The trace also
contains `claims.hybrid_investigation` with `rag.policy_evidence_status=retrieved` and
`ml.advisory_status=available`, plus the risk advisory span. The agent recorded 8 sources and 3 tool
calls. No `rag.generate` span is expected because RAG runs in retrieval-only mode; the agent
generates the final brief. The October 6 trace above belongs to the prior optional-RAG behavior and
is not used as evidence for this amendment.