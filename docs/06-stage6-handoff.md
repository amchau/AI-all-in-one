# Stage 6 Handoff

Updated: 2026-10-07
Status: Mandatory retrieval is implemented, deployed, and trace-verified; answer-quality review remains open.

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

1. Add a fixed combined-workflow regression case for the pipe-failure narrative. Assert that retrieval
   includes the expected water-clarification source, or returns an explicit uncertainty state if it
   cannot. Cover the flood extension separately: without schedule data, require an unresolved
   question, not an applicability claim.
2. Check whether the retrieval query/ranking is missing relevant endorsements. Use the annotated Stage
   2 golden sources as evidence; a `retrieved` status alone is not a recall metric.
3. Verify summary/findings cite returned source IDs and do not assert policy-period validity without
   expiry evidence. Keep claim decision authority with the handler.
4. Run focused and full tests, then one approved synthetic provider-backed smoke with no automatic
   retry. Confirm expected source IDs, evidence status, response trace ID, and RAG/agent/risk spans.
5. Update this handoff, the Stage 6 plan/report, and roadmap status only after those checks and user
   review. Do not claim real-world risk quality or production readiness.

## Verified checks

- Python 3.12 backend unit/integration: 315 passed, 2 skipped.
- Focused claims/agent/RAG coverage: 87%.
- Frontend: 15 tests passed, 98.8% line coverage, production build passed.
- Playwright desktop/mobile: 6 passed.
- Python compilation, shell syntax, Kustomize rendering, and `git diff --check` passed.
- Stage 6 API/frontend images built and loaded; live trace above confirms the mandatory-retrieval API
  path is deployed.