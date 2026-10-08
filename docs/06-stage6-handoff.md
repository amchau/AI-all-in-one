# Stage 6 Handoff

Updated: 2026-10-08
Status: **Done for the user-reviewed local synthetic scope.** Mandatory retrieval, the deterministic answer guard, and JSON-mode final response were exercised on pipe-failure and CL-125 flood scenarios. This is not a general model-quality or production-readiness claim. The kind cluster was recovered with preserved PVC data.

## Current behavior

- `POST /v1/claims/hybrid-investigations` resolves authoritative claim, policy, and loss-date context.
- The API runs one retrieval-only `hybrid_rerank` query before the bounded agent. It passes returned
  policy chunks into the agent as validated, source-linked, untrusted context. The RAG answer
  generator is skipped; the agent produces the final brief.
- Policy evidence has a distinct `retrieved`, `insufficient_evidence`, or `unavailable` status.
  RAG failure does not prevent the agent/risk path from returning a partial result.
- Stage 5 risk inference remains server-owned and separate from policy sources and findings.
- The Stage 4 agent-only endpoint retains its optional RAG tool behavior.

## Live trace

Trace `0826761b079e1dfc1e0de72aadca0b8d` (2026-10-07) returned
`policy_evidence_status=retrieved`. Collector spans include `rag.source_resolution`, `rag.embed`,
`rag.sparse_embed`, `rag.search`, `rag.rerank`, `claims.hybrid_investigation`, and the risk advisory.
Reranking processed 20 candidates and returned 20 results; the agent registered 8 sources and made
3 tool calls. `rag.generate` is absent by design because retrieval-only mode skips RAG answer
generation.

This proves retrieval executed and returned evidence. It does not by itself prove that all relevant
clauses were retrieved or that every generated statement is fully supported.

## Review finding

The returned sources included HOME-002 base wording, procedures, and regulation, but omitted two
synthetic HOME-002 endorsements that are effective by the 2025-03-01 loss date:

- The water clarification endorsement is relevant to distinguishing sudden pipe escape from gradual
  leakage.
- The flood extension replaces base clause 4.2 only when listed on the policy schedule. The current
  claim fixture has no schedule, so applicability must remain unresolved; do not infer that it is
  present or absent.

The response also said the loss date was "within the policy period," although the registry contains
an effective date but no expiry date. It left `unresolved_questions` empty despite missing schedule
and cause/duration evidence. See [the detailed integration report](eval/stage6-hybrid-ai-report.md)
and [the Stage 2 golden set](../tests/evaluation/golden.yaml).

Acceptance status: user reviewed and accepted the pipe-failure and CL-125 flood schedule-uncertainty
scenarios on 2026-10-08 for the local synthetic scope. Retrieval/status handling, trace correlation,
returned-source identity, JSON-mode final output, schedule uncertainty, and separate risk advice were
verified for these scenarios. This acceptance is limited to the tested fixtures and is not a broad
semantic-faithfulness or production-readiness claim.

## Closeout and Follow-Ups

- User reviewed and accepted the tested local synthetic pipe-failure and CL-125 flood scenarios on
  2026-10-08. The flood answer leaves applicability unresolved because schedule evidence is absent.
- Retain the historical failures below for diagnosis. They were addressed for the reviewed scope by
  `top_k=8`, the deterministic answer guard, JSON-object final mode, and the 60-second final-turn
  timeout; no automatic retries were added.
- Broader semantic reliability, additional flood variants, real claims, and production readiness are
  outside this acceptance. Treat any expansion as a new review/evaluation scope.

## Verified checks

- Python 3.12 backend unit/integration: 315 passed, 2 skipped.
- Focused claims/agent/RAG coverage: 87%.
- Frontend: 15 tests passed, 98.8% line coverage, production build passed.
- Playwright desktop/mobile: 6 passed.
- Python compilation, shell syntax, Kustomize rendering, and `git diff --check` passed.
- Stage 6 API/frontend images built and loaded; live trace above confirms the mandatory-retrieval API
  path is deployed.
- Follow-up regression (2026-10-07): claims-agent prompt and combined API unit slices passed (36
   tests); Python 3.12 full backend unit/integration suite passed (315 passed, 2 skipped). The pipe-
   failure test uses a fake retrieval result; the later live trace diagnosis above separately
   confirms the endorsements enter candidates but miss the returned top five.
- Answer-guard follow-up (2026-10-07): claims-agent/API tests passed (39); full Python 3.12 backend
   unit/integration passed (318 passed, 2 skipped). The correlated `top_k=8` smoke still returned
   unsupported coverage prose, which is now covered by three local fail-closed regressions. The
   stricter detector image was rebuilt and rolled out successfully.
- Guard smoke (2026-10-07): one approved request returned HTTP 200, `policy_evidence_status=retrieved`,
   `investigation.status=insufficient_evidence`, empty summary/findings, required schedule/expiry/
   cause-duration questions, and available risk. Response/collector trace `191bd56770048eb4933bd5520b25060f`
   matched; spans confirmed `top_k=8`, 32 candidates, eight returned policy chunks, three agent tool
   calls, and the risk advisory. No retry or additional request was made.
- Flood retrieval probe (2026-10-07): trace `93d95eacf204ae853dc11b50bbefd5ff` shows the flood
   extension ranked 1st and 2nd after reranking and was returned in top eight. The API returned 502
   during agent execution; Groq rejected malformed `submit_final_answer` arguments with
   `tool_use_failed` on turn 3. No answer or policy-applicability result was available. No retry was
   made. Local route regression plus full backend suite passed (320 passed, 2 skipped).
- Cluster recovery (2026-10-08): kind v0.33.0 had no cluster; the detached Podman volume labeled
   `ai-stage1-control-plane` was preserved. Its four PVC directories were archived to
   `~/.local/state/ai-all-in-one/recovery/stage6-pvcs-2026-10-08.tar.gz` (SHA-256
   `6c0144a2cb3c8d3272705e963e54a1130b8d50c1c653c2812e0a6ffb4b73bb24`), extracted separately, and
   mounted into the new control-plane node using local Retain PVs. All workloads are ready; Qdrant
   reports 44 points, Postgres registry has 8 documents, and `rag-ingest` remains suspended. The
   original 11 GB node volume is untouched. No provider-backed smoke was run during recovery.
- Flood fixture readiness (2026-10-08): `CL-125` and its fixed risk vector are served by the recovered
   claims service; local route regression proves schedule uncertainty. No provider-backed flood answer
   was requested during this fixture work.
- CL-125 live flood check (2026-10-08): HTTP 200, retrieved flood-extension evidence, available risk,
   and an explicit unresolved schedule-applicability question. Response trace
   `c0a716677588af2a910311f11d6becc1` matches collector spans; four JSON-mode agent turns succeeded.
   No retry was made.
- JSON-mode live verification (2026-10-08): one synthetic `CL-123` pipe-failure request returned
   HTTP 200, retrieved policy evidence, `investigation.status=insufficient_evidence`, empty
   summary/findings, required schedule/expiry/cause-duration questions, and available risk. Response
   trace `23bbdc99d267ebeddabcdea57c9cb48f` matches the collector; all four agent turns reported
   `llm.status=ok`, with two tool calls and ten total sources. No retry was made. This verifies JSON
   final output and the guard on one synthetic pipe-failure scenario only.