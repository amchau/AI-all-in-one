# ADR-009 - Dense RAG Query Contract

## Status

Accepted (2026-10-03)

## Context

Phase 2.2 stores policy-document chunks and 1536-dimensional dense vectors in Qdrant,
document metadata and effective dates in PostgreSQL, and original PDFs in MinIO. Phase 2.3
adds the first online query path. Answers must be traceable to retrieved clauses and must not
turn retrieval similarity into an uncalibrated coverage decision.

The current registry has effective start dates but no expiry, supersession, or precedence
fields. The API currently uses bootstrap PostgreSQL credentials, which are too broad for
query-time source resolution.

## Options

| Concern | Chosen | Alternative |
|---------|--------|-------------|
| Retrieval mode | Dense-only against the existing named `dense` vector | Implement sparse/BM25 and reranking in this phase |
| Policy time | Latest base policy effective on/before loss date; matching endorsements effective by that date | Caller-managed document IDs or defer version filtering |
| Guidance time | Separate `guidance_as_of`, defaulting to `loss_date` | Apply one date to all document types |
| Citation integrity | Require inline chunk refs per claim and validate them server-side | Trust model-produced citations or return all hits as citations |
| Insufficient evidence | No usable hits, explicit model abstention, or invalid citation output | Use an uncalibrated dense score threshold |
| Database identity | Dedicated read-only `rag_query` role with metadata column grants | Reuse the API's bootstrap account |

## Decision

- Expose `POST /v1/rag/query` with a required question, `policy_id`, and `loss_date`, optional
  `guidance_as_of` (default `loss_date`), bounded `top_k` (default 5), and fixed `mode: dense`.
- Select the latest base policy with the requested `policy_id` effective on or before `loss_date`.
  Include matching endorsements effective by that date. Include relevant policy-specific or
  global procedure/regulatory sources effective by `guidance_as_of`, matching the selected
  product or `all`.
- Fail closed when no base policy applies or multiple base policies share the latest applicable
  effective date. Current data cannot represent expiry, supersession, or legal precedence; this
  phase does not infer those rules.
- Embed query text through LiteLLM alias `embed-small` and retrieve only from Qdrant's named
  `dense` vector, filtered to the resolved source document IDs.
- Require structured answer claims with inline refs to retrieved chunk IDs. Validate every ref
  against the retrieved set and map it to document, section, clause, and page. Referential
  validation does not prove semantic entailment; Phase 2.5 evaluation measures faithfulness.
  Return no answer text for abstention, no usable results, or invalid citations.
- Do not use a dense similarity cutoff until the Phase 2.5 evaluation set can calibrate it.
  Infrastructure and model failures are sanitized service errors, not abstentions.
- Use `rag_query` for API health/source metadata reads. It receives only the column-level SELECT
  privileges required on `rag.documents`, via an isolated Kubernetes Secret. Provisioning clears
  inherited PUBLIC/schema/relation/routine/sequence grants and rejects object ownership by the
  query role; the dedicated platform database revokes PUBLIC CONNECT/CREATE/TEMP and public-schema
  access.
- Query execution is read-only against Postgres, Qdrant, and MinIO. Hybrid/BM25, reranking,
  evaluation comparisons, real ACL enforcement, and claim decisions remain outside Phase 2.3.
- API readiness checks Qdrant service availability, not whether ingestion has already created the
  `insurance_docs` collection. This preserves `/v1/investigate` availability before first ingest;
  RAG calls fail closed if the collection is absent or incompatible.
- The endpoint remains cluster-internal and unauthenticated for this synthetic local lab. Do not
  expose it to untrusted callers or restricted documents before authentication and ACL enforcement.
- Bound generated output to 800 completion tokens, at most 20 claims, and 2,000 characters per
  claim; unit validation rejects larger output.

## Validation

- Unit-test effective-date selection, Qdrant filters, input bounds, citation validation, abstention,
  malformed responses, and sanitized failures.
- Verify the `rag_query` role cannot write and can read only required metadata.
- Run an opt-in cluster query against the 2.2 corpus. Every returned inline citation must map to a
  returned chunk; Postgres document and Qdrant point counts must be unchanged.
- Smoke one answerable HOME-002 question through the deployed endpoint before marking Phase 2.3
  complete.

## Consequences

- Positive: answers carry machine-checkable, clause-level source refs; query-time DB permissions
  are separated from ingestion and bootstrap identities; the 2.2 index is reused without writes.
- Negative: both loss and guidance dates are explicit concepts; model JSON compliance must be
  validated; ambiguous versions are refused rather than guessed; valid refs can still cite
  semantically irrelevant chunks, which requires evaluation rather than referential checks alone.
- Follow-up: add expiry/supersession and precedence data only through a future documented schema
  decision. Calibrate evidence thresholds in Phase 2.5.