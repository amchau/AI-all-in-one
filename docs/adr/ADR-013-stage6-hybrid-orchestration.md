# ADR-013 - Stage 6 Hybrid Claims Orchestration

## Status

Accepted (user approval: 2026-10-06)

## Context

Stage 6 combines a bounded claims agent, temporal hybrid RAG evidence, and the Stage 5 synthetic
human-review referral model. These currently have separate contracts. Stage 5 inference requires
five bounded numeric features that are not part of the claims-service record. Its output is advisory
and carries synthetic-label limitations. The integration must not let an LLM choose risk calls or
present the risk result as evidence, fraud determination, or claim outcome.

## Options

| Concern | Chosen: deterministic separate advisory | LLM-selected risk tool | Risk result in agent context |
|---------|------------------------------------------|------------------------|------------------------------|
| Invocation | Server invokes after claim resolution | Model decides whether to invoke | Server invokes, then exposes result to model |
| Safety boundary | Risk cannot shape findings or citations | Adds a model-controlled action surface | Needs prompt/output rules against unsupported claims |
| Evaluation | Contract, failure isolation, and output separation | Must measure tool selection and prohibited behavior | Must evaluate agent interpretation of risk |
| Operations | One bounded internal HTTP call | Adds tool schema and tool-budget usage | Adds prompt tokens and another dependency in agent path |

| Feature source | Chosen: fixed fixture-owned values | Caller-supplied values | Narrative-derived or model-derived values |
|----------------|----------------------------------|----------------------|-----------------------------------------|
| Provenance | Deterministic, reviewable synthetic inputs | Caller controls model inputs | Hard to verify; changes Stage 5 semantics |
| Contract | Internal typed lookup endpoint | Expands user request schema | Couples model inputs to language interpretation |
| Failure behavior | Explicit feature service dependency | No separate feature ownership | Inference may invent or inconsistently derive inputs |

| Failure policy | Chosen: preserve investigation; mark risk unavailable | Fail whole request | Force triage on outage |
|----------------|-----------------------------------------------|-------------------|-------------------------|
| Evidence availability | Preserved during ML outage | Coupled to ML readiness | Preserved but changes triage semantics |
| User interpretation | Explicit unavailable status/reason | Simple single request state | Conflates service failure with model uncertainty |

## Decision

- Add a new `POST /v1/claims/hybrid-investigations` contract and preserve the Stage 3
  `/v1/investigations` and Stage 4 `/v1/claims/agent-investigations` contracts.
- Accept claim ID, narrative, and optional guidance date. Resolve policy ID and loss date from the
  synthetic claims service.
- Extend fixed synthetic fixtures with explicit values conforming to Stage 5's existing
  `ClaimRiskFeatures` schema. Expose values through a typed internal endpoint, separate from the
  agent's claim-record tool.
- Run hybrid RAG retrieval deterministically before the Stage 6 agent, then call risk inference
  deterministically after it. Pass retrieved chunks as validated source-linked initial context to
  the bounded agent; do not run a separate RAG answer-generation call. Keep risk data out of LLM
  prompts, tools, findings, citations, and retrieved evidence.
- Compose agent output and risk result as separate fields in the combined response. If feature lookup
  or risk inference fails, preserve the investigation and return a bounded unavailable status and
  reason. Do not reinterpret an unavailable response as low risk or handler triage.
- Update the existing frontend to use the combined route and show an independent advisory panel.
- Retain Stage 5 model, feature rubric, thresholds, and evaluation unchanged. Do not claim real-world
  fraud or operational performance.

## Validation

- Test feature lookup identity/schema/ranges and unknown-claim behavior.
- Test combined endpoint success, malformed feature/risk responses, timeouts, upstream failures,
  and preservation of the investigation on risk outage.
- Verify risk is not exposed as a model tool and does not enter the agent prompt or source set.
- Test guidance-date propagation and existing endpoint backward compatibility.
- Verify every combined investigation invokes retrieval once before the agent, including when no
  chunks match; verify dependency/source-selection failures are distinguished from empty results.
- Verify frontend priority, routine, triage, and unavailable states on desktop/mobile.
- Correlate a single synthetic end-to-end trace and inspect spans/logs for absence of narrative, raw
  features, labels, and PII.

## Consequences

Positive:

- Keeps model output advisory and separate from sourced investigation evidence.
- Reuses the existing bounded agent, RAG, and inference service boundaries.
- Makes risk inputs explicit and reproducible without accepting them from the browser.
- Keeps the investigation usable when the risk service is temporarily unavailable.

Negative:

- Adds a feature lookup and risk-service network call and associated failure states.
- Synthetic features and labels remain illustrative and do not establish real claim risk.
- The current local environment remains unauthenticated and unsuitable for real data.

Follow-up:

- Any future real-data use, change in model target, caller-supplied feature contract, LLM-selected
  risk tooling, or decision authority requires a new reviewed plan/ADR and independent evidence.

## Decision Amendment - Mandatory Stage 6 Retrieval (2026-10-07)

The initial Stage 6 smoke returned claim, policy-record, and customer sources but no policy wording;
the trace had no RAG spans because the combined route exposed RAG as an optional model-selected tool.
The user selected deterministic retrieval for every combined investigation.

- Resolve the authoritative claim context first, then run `hybrid_rerank` retrieval once before
  starting `ClaimsAgent`. Use the optional guidance date when present, otherwise the claim loss date.
- Use retrieval-only mode: resolve eligible documents, embed through LiteLLM, search Qdrant, rerank
  through TEI, and return bounded validated chunks. Do not run RAG answer generation; the agent
  makes the final structured brief using those source-linked chunks.
- Seed the agent's initial user context/source registry with retrieved policy evidence as untrusted
  data. The combined route does not expose `get_policy_evidence` as a second model-selectable tool.
  Preserve the optional Stage 4 agent-only route behavior.
- Return `policy_evidence_status` as `retrieved`, `insufficient_evidence`, or `unavailable`; include
  a bounded reason only for unavailable source selection/retrieval. Continue the agent when RAG is
  unavailable, but never describe that state as a successful empty search.
- Acceptance now requires tests for one retrieval before agent execution, guidance-date forwarding,
  source-ID validation, zero-hit status, and retrieval/source-selection failure status. A live
  provider-backed RAG smoke remains separately gated; do not repeat one without an approved scenario.

Live verification (2026-10-07): the user reported `policy_evidence_status=retrieved` for trace
`0826761b079e1dfc1e0de72aadca0b8d`. Collector inspection confirmed RAG source resolution, dense and
sparse embedding, hybrid search, reranking, combined investigation status `retrieved`, and risk
status `available`. Reranking processed 20 candidates and returned 20 results. Retrieval-only mode
correctly emitted no `rag.generate` span. See the [Stage 6 evaluation report](../eval/stage6-hybrid-ai-report.md).

Implementation note (2026-10-07): `RagQueryService` has a retrieval-only mode, the combined route
retrieves before constructing the agent, and validated policy chunks are seeded into the agent's
source registry and initial context. The existing Stage 4 endpoint retains its optional RAG tool.
The October 6 live smoke predates this amendment and does not verify mandatory retrieval.