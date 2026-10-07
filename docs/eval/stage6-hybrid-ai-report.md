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

## Pipe-Failure Regression Follow-Up (2026-10-07)

The combined API regression now uses the fixed narrative "A domestic pipe failed overnight and water damaged the home; duration is unknown." Its mocked retrieval returns the HOME-002 water clarification and flood extension. The test asserts both document identities are passed to the agent, the summary cites the water clarification source, and schedule applicability plus cause/duration remain unresolved. The claims-agent system prompt now explicitly prohibits inferring schedule-dependent endorsement applicability and policy-in-force from an effective date without expiry evidence.

The prompt-contract and combined API unit slices passed (36 tests); the full Python 3.12 backend unit/integration suite passed (315 passed, 2 skipped). These are prompt/orchestration contract checks, not a test of actual retrieval ranking or model adherence. At the time of that follow-up, no provider-backed smoke had run. Retrieval coverage, live answer completeness, and Stage 6 answer-quality acceptance therefore remained open.

## Ranked-Document Diagnostic (2026-10-07)

Added bounded ordered document-ID attributes to `rag.search` (`rag.candidate_doc_ids`) and `rag.rerank` (`rag.reranked_doc_ids`, `rag.returned_doc_ids`). They contain corpus IDs only, never query text, chunk text, or claim data. The focused retrieval suite passed (32 tests); full Python 3.12 backend unit/integration passed (315 passed, 2 skipped). API image `localhost/ai-api:stage6.0` was rebuilt, loaded, and rolled out successfully.

One approved request used claim `CL-123`, narrative "A domestic pipe failed overnight and water damaged the home; duration is unknown.", and guidance date `2026-01-01`. Trace `dd6a3694ea907d170e60b9c592dfaf30` showed 20 hybrid candidates and 20 reranked chunks. Both expected endorsements entered the candidate set: water-clarification chunks appeared at candidate ranks 3, 7, 11, and 13; flood-extension chunks at 8 and 17. After reranking, water chunks ranked 7, 8, 10, and 14; flood chunks ranked 12 and 19. The returned top five were the base policy, three water-procedure chunks, and the regulation. The observed omission is therefore rerank ordering plus the combined route's `top_k=5` cutoff, not source eligibility or absent indexed chunks.

This request returned HTTP 502 because LiteLLM rejected the agent chat-completion request with HTTP 400 on model turn 4. No retry was made. It diagnoses retrieval ranking only; it does not verify a completed answer or whether the updated prompt rules are followed. Stage 6 answer-quality acceptance remains open. The next implementation decision is a bounded Stage 6 evidence-selection policy that preserves relevant endorsement chunks while respecting the agent's maximum of eight initial sources, followed by a regression and a separately approved smoke.

## `top_k=8` Pipe-Failure Answer Review (2026-10-07)

The user-reported synthetic request returned HTTP 200 with `policy_evidence_status=retrieved`, eight policy chunks including two from `END-HOME-002-WATER-LIMIT-02`, summary citations to base-policy section 3 and water-endorsement section 3, three tool calls, and an available risk advisory. This supports the bounded retrieval change for the water-clarification source in this scenario. The flood extension was not in the returned sources.

The reported summary nevertheless asserted the repair-cost schedule content and that the loss is covered under the escape-of-water clause. The synthetic policy record has `status=active` and an effective date, but no expiry date or schedule data. The endorsement applicability is conditional on schedule listing. Although the answer asked schedule, expiry, and cause/duration questions, its unsupported affirmative assertions remain an answer-quality failure despite valid source IDs.

The response trace ID is `b97fe7dbe3fbf9fb59b17bf6281bf851`, and the collector trace matches. It shows `top_k=8`, 32 hybrid candidates, both endorsements among candidates, two water-endorsement chunks in the returned eight, 11 total agent sources, three tool calls, successful agent spans, and available risk advisory.

A deterministic Stage 6 output guard was expanded after this response. It requires unresolved questions for absent schedule, expiry, and cause/duration evidence, and converts detected unsupported policy-period, schedule, coverage, and endorsement assertions into an `insufficient_evidence` result with empty summary/findings. Three local regressions cover the exact unsupported claim forms; the full Python 3.12 backend suite passed (318 passed, 2 skipped). The stricter detector was built and rolled out locally.

## Guarded Pipe-Failure Smoke (2026-10-07)

One explicitly approved request to the updated deployment returned HTTP 200, `policy_evidence_status=retrieved`, and `investigation.status=insufficient_evidence`. The guard returned an empty summary and findings, and unresolved questions included schedule applicability, expiry/lapse, cause/duration, leak duration, and repair cost. Water-endorsement chunks remained in the returned policy evidence; risk status was available.

Response trace `191bd56770048eb4933bd5520b25060f` matches the collector trace. Spans confirm retrieval-only hybrid reranking with `top_k=8`, 32 candidates, eight returned policy chunks, three agent tool calls, and the risk advisory. No retry or second request was made. This verifies the guard for this one synthetic pipe-failure response; flood-extension retrieval/applicability and broader answer quality remain open.

## Flood-Extension Retrieval Probe (2026-10-07)

One synthetic flood-focused request used `CL-123` with a surface-water-runoff narrative. Trace `93d95eacf204ae853dc11b50bbefd5ff` confirms `top_k=8`, 32 hybrid candidates, and the flood-extension document at reranked positions 1 and 2; both chunks were in the returned top eight. This confirms the retrieval path can surface the flood extension for this query.

The API returned HTTP 502 during agent execution with `AgentDependencyError`; no investigation answer, citations, or risk result were returned. Gateway logs show Groq returned HTTP 400 `tool_use_failed` because the `submit_final_answer` arguments were malformed on model turn 3. No retry was made. The narrative also conflicts with the `CL-123` fixture's reported pipe failure, so this is a retrieval probe only, not an answer-quality or coverage evaluation.

A route-level regression now supplies the retrieved flood extension to a fake agent that asserts it applies without schedule evidence; the Stage 6 guard returns `insufficient_evidence` and inserts the schedule question. Claims-agent/API tests passed (41), and the full Python 3.12 backend suite passed (320 passed, 2 skipped). A coherent flood fixture/live answer-level verification remains open and requires a stable agent dependency plus a separately approved smoke.

## Final-Response Transport Fix (2026-10-07)

The agent no longer forces Groq to serialize final output as a `submit_final_answer` tool call. The final turn supplies no tools and requests `response_format: {"type":"json_object"}`. The returned content is still parsed as `AgentFinalPayload`, then validated against the returned source IDs; malformed JSON or unexpected final tool calls fail closed. The focused claims/API suite passed (41 tests), and the full Python 3.12 backend suite passed (320 passed, 2 skipped).

One authorized live check against this JSON mode returned HTTP 502 after final model turn 4 exceeded the existing 30-second read timeout. Earlier agent turns succeeded; the malformed tool-call rejection did not recur. The final JSON request now uses a bounded 60-second timeout, while intermediate turns remain at 30 seconds and automatic retries remain disabled. This timeout follow-up has been deployed locally but has not produced a successful provider-backed response.
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