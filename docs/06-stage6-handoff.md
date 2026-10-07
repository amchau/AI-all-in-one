# Stage 6 Handoff

Updated: 2026-10-07
Status: Mandatory retrieval is implemented; Stage 6 `top_k=8` retrieved the water clarification, and the stricter deterministic answer guard passed one live pipe-failure smoke. Flood-extension coverage and broader answer-quality review remain open.

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

Acceptance status: mandatory retrieval, status handling, trace correlation, and citation-to-returned-
source identity pass. Retrieval coverage and answer completeness are **partial** for this smoke.
Do not mark Stage 6 answer-quality acceptance complete yet.

## Next steps

1. **Regression added, retrieval still mocked:** the fixed pipe-failure route test asserts the water
   clarification and flood extension source identities propagate to the agent, verifies the summary
   cites the water source, and keeps schedule/cause/duration questions unresolved. Agent prompt rules
   now explicitly forbid inferring schedule-dependent applicability or policy-in-force from an
   effective date alone. These tests do not prove that live ranking retrieves the endorsements or
   that a model follows the prompt.
2. **Live ranking diagnosis completed (2026-10-07):** trace
   `dd6a3694ea907d170e60b9c592dfaf30` shows both endorsements in the 20 Qdrant candidates. After
   reranking, water-clarification chunks occupied positions 7, 8, 10, and 14; flood-extension
   chunks occupied positions 12 and 19. The final five were base policy, three water-procedure
   chunks, and regulation. This isolates the observed missing-endorsement behavior to rerank ordering
   plus the Stage 6 `top_k=5` cutoff, not date eligibility or absent index chunks. The trace has
   bounded document IDs, not chunk text.
3. **`top_k=8` smoke and answer review (2026-10-07):** the user reported HTTP 200, retrieved policy
   evidence, two water-endorsement chunks in the returned eight, three tool calls, and available
   risk. The answer incorrectly asserted the repair-cost schedule content and coverage under the
   escape-of-water clause, despite missing schedule evidence. It did ask schedule, expiry, and
   cause/duration questions. The response trace `b97fe7dbe3fbf9fb59b17bf6281bf851` matches the
   collector trace and confirms top-k 8, 32 candidates, eight returned chunks, and successful
   agent/risk spans.
4. A deterministic guard forces expiry, schedule, and cause/duration questions from typed source
   gaps and abstains on detected unsupported policy-period, schedule, coverage, or endorsement
   claims. It passed one live pipe-failure smoke: response and collector trace IDs matched, the
   investigation abstained with empty summary/findings, and risk remained available.
5. **Flood probe (2026-10-07):** one synthetic request placed the flood extension in rerank positions
   1 and 2 and in the returned top eight, confirming query-specific retrieval. The request then
   returned HTTP 502 during agent execution (`AgentDependencyError`); no answer was produced and no
   retry was made. It used `CL-123` but a flood narrative that conflicts with the fixture's reported
   pipe failure, so treat it as a retrieval probe only. Trace:
   `93d95eacf204ae853dc11b50bbefd5ff`. Gateway logs show Groq `tool_use_failed`: malformed
   `submit_final_answer` arguments on agent turn 3.
6. A local combined-route regression now feeds the flood endorsement to a fake agent that asserts
   applicability; the API returns `insufficient_evidence` and requires the schedule question. Claims
   API tests: 41 passed; full Python 3.12 backend: 320 passed, 2 skipped.
7. Add live answer-level flood-extension applicability verification with a coherent synthetic
   fixture and stable agent dependency. The schedule question must remain unresolved unless
   schedule evidence is present. The flood probe authorization has been used; seek explicit
   approval before another provider-backed request. Do not claim real-world risk quality or
   production readiness.
8. Groq's malformed final tool-call path is replaced locally with tool-free JSON-object mode on the
   final turn; the same typed payload and source-ID validation remain. One live check reached JSON
   mode successfully, but final turn 4 hit the 30-second read timeout. The final JSON request now has
   a 60-second bounded timeout; intermediate calls remain at 30 seconds, with no retry. Claims/API
   tests pass (41), full backend passes (320 passed, 2 skipped). The 60-second timeout image is
   deployed, but no successful live response has verified it. Stage 6 remains open; seek approval
   before another provider-backed check.

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