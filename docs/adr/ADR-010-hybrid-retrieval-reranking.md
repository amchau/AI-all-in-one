# ADR-010 - Hybrid Retrieval and Reranking Contract

## Status

Accepted (2026-10-03)

## Context

Phase 2.3 established a dense-only query path over Qdrant collection `insurance_docs`, with
temporal source filtering, grounded generation, and validated citations. Phase 2.4 adds lexical
matching for exact terms and identifiers, then an optional cross-encoder rerank. The existing
44 points and registry fingerprints describe dense-only vectors, so the migration must be
idempotent and must not discard the live collection or deterministic point IDs.

## Decisions

- Use FastEmbed `Qdrant/bm25` for sparse passage and query encoding. Store it as the named `sparse`
  vector alongside the existing named `dense` vector in Qdrant.
- Pin Qdrant server and Python client to `1.19.1`. Qdrant's named-vector create API is available from
  server `1.18.0`; the current `1.15.4` server cannot add a missing sparse vector through
  `update_collection`.
- Upgrade persisted Qdrant data in supported hops: `1.15.4` -> `1.16.3` -> `1.17.1` -> `1.18.3`
  -> `1.19.1`. Require a downloaded collection snapshot before the guarded upgrade helper runs.
- Include sparse model identity and vector-schema revision in ingestion fingerprints. Use
  `create_vector_name` to add sparse configuration to the existing collection in place, then rebuild points through the normal
  ingestion Job. Preserve document/chunk IDs and assert that the subsequent run is a no-op.
- Use Qdrant's native Query API with equally weighted dense and sparse prefetches, each filtered by
  the same source-document allowlist, and fuse with RRF. Do not compare raw dense and BM25 scores
  or tune weights without Phase 2.5 evaluation.
- Keep API `top_k` as the maximum number of returned chunks. Hybrid prefetches use
  `min(50, max(20, 4 * top_k))` candidates. `hybrid` returns the fused top `top_k`; `hybrid_rerank`
  reranks the bounded fused candidate set with the existing TEI service and then returns top `top_k`.
- Keep `dense` as the default and add `hybrid` and `hybrid_rerank`. Return the effective mode and
  preserve the existing `score` field as the final ranking score. Add optional named fields:
  `dense_score` for dense mode, `hybrid_score` for fused hybrid ranking, and `rerank_score` for TEI
  ranking. For reranked results preserve `hybrid_score` and make `score` equal `rerank_score`.
  Do not repeat searches to expose dense/sparse prefetch scores that Qdrant's fused result omits.
- A requested rerank that cannot complete fails with a sanitized dependency error. It does not
  silently fall back to hybrid, so the requested mode and measured behavior remain truthful.
- Preserve source selection, bounded answer generation, citation validation, abstention, and
  read-only query behavior from ADR-009. Generate against the final ordered chunks and assign
  citation refs after reranking.
- Add sparse-encoding and `rag.rerank` spans. Record the sparse/reranker model, mode, candidate and
  result counts, ranking scores, and latency; never record raw question or evidence text.
- Phase 2.4 verifies functionality. Phase 2.5 evaluates dense vs hybrid vs hybrid+rerank and owns
  quality claims, thresholds, and any score/fusion tuning.

## Consequences

- Positive: exact-term recall is added without replacing semantic retrieval; final generation and
  citations remain tied to the displayed result order; the existing collection and point identity
  remain stable across migration.
- Negative: Qdrant requires a staged stateful upgrade before migration; ingestion and query images
  include a sparse encoder dependency; the first use may need
  to populate its model/tokenizer cache; reranking adds CPU latency and a dependency failure mode.
- Follow-up: measure retrieval quality, citation accuracy, and p95 latency on the Phase 2.5 golden
  set before claiming a quality improvement or changing RRF weights.

## Decision Amendment - Generation Bounds (2026-10-04)

### Evidence

- The deployed smoke test returned cited answers for `dense` and `hybrid_rerank`.
- `hybrid` returned `insufficient_evidence` at `top_k=5` and a cited answer at `top_k=8`.
- A diagnostic `hybrid` request at `top_k=20` returned HTTP 502. LiteLLM logs show Groq's
  `json_validate_failed` error with an empty `failed_generation`; no `finish_reason` or token usage
  was returned. This does not establish that the 800-token completion limit caused the failure.

### Decision

- Keep request `top_k` unchanged: it controls retrieval and the chunks returned to clients, up to 20.
- Bound initial grounded generation context to the first 8 whole chunks in final retrieval order.
  Do not truncate chunks or alter the returned chunk list. The current chunker caps a chunk at 400
  `cl100k_base` tokens, so this bounds evidence text to at most approximately 3,200 tokens before
  prompt and JSON overhead.
- If and only if LiteLLM reports Groq's allowlisted `json_validate_failed` error, retry generation
  once with the first 4 whole chunks. Do not retry transport errors, 5xx responses, other 4xx
  errors, or successful responses containing malformed application JSON.
- If the retry also fails, return the existing sanitized dependency error (HTTP 502). Do not turn
  a provider failure into `insufficient_evidence`; that status remains for model abstention, no
  usable evidence, or invalid citations after a successful generation response, per ADR-009.
- Keep `max_completion_tokens=800` for this change. Record completion usage and `finish_reason`
  when the provider returns them. Revisit the cap only with a controlled LiteLLM replay and
  evidence that the response hit the completion limit; do not call Groq directly.
- References remain those assigned to the complete returned ranking. Generation may cite only
  refs in its bounded evidence subset, and the normal server-side citation validation still runs.

### Validation

- Unit tests prove `top_k=20` still returns 20 chunks while generation first receives at most 8;
  a Groq JSON-validation failure retries once with at most 4 chunks and validates citations
  against that retry's evidence.
- Unit tests prove unrelated upstream failures are not retried, two JSON-validation failures
  remain sanitized dependency errors, and an explicit model abstention remains
  `insufficient_evidence`.
- After deployment, repeat the same `top_k=20` hybrid query through LiteLLM-backed API and verify
  no 502, response size is bounded by `top_k`, and every citation maps to a returned chunk.
- Phase 2.5 measures whether this context policy harms recall/faithfulness; 8/4 are operational
  bounds, not a claim of optimal answer quality.

### Live follow-up (2026-10-05)

Rebuilt and rolled out only the `ai-api` Deployment. One `hybrid` request at `top_k=20` returned
HTTP 200 with an answered status, 20 chunks, and 2 citations; both citations mapped to returned
chunks. Latency was 1774 ms. Trace `687a78b6c8a6ea8cd3d56d1305841911` was found in collector output
with `rag.source_resolution`, `rag.embed`, `rag.sparse_embed`, `rag.search`, `rag.generate`, and
`rag.query` spans. Together with the unit tests above, this closes the follow-up. It verifies the
bounded-generation operational behavior for this request, not comparative answer quality; that
remains the scope and limitation of Phase 2.5's evaluation.