# Stage 2 - Insurance Knowledge System (Enterprise RAG)

Status: **IN PROGRESS** - Phase 2.5 evaluation complete; Phase 2.6 observability + docs is next; Phase 2.4 top_k=20 generation follow-up remains open
Pattern: #1 Enterprise RAG / Knowledge Intelligence
Builds on: Stage 1 platform (kind, LiteLLM -> Groq, Qdrant, Postgres, MinIO, OTEL)

## 0. Problem statement

A claims handler at a UK personal-lines insurer (home, motor, small commercial) must decide
whether a loss is covered. The answer is spread across several documents:

- base policy wording (product + version in force on the loss date)
- endorsements that add, remove or override base clauses
- internal claims procedures (evidence required, escalation thresholds)
- regulation: FCA ICOBS 8 (handle claims promptly and fairly, do not unreasonably reject,
  give reasonable guidance on progress) and Consumer Duty fair-outcome expectations

Pain today: manual search across PDFs, wrong wording version, missed endorsements,
subtle exclusions (flood vs escape of water vs gradual seepage). Result: slow handling,
inconsistent outcomes, and unreasonable rejections that lead to complaints and Financial
Ombudsman Service cases.

Stage 2 outcome: for a question scoped to a policy, return the exact governing clauses and
a cited answer, or say evidence is insufficient. It informs the handler; it does not decide
the claim (that is Stage 3 copilot + human approval).

Success measures: correct clause in top 5 (recall@5), citation accuracy, no uncited claims,
correct "insufficient evidence" on unanswerable questions, p95 latency.

Regulatory text in the corpus is a synthetic paraphrase of ICOBS 8 themes, not copied FCA text.

## 1. What we are building

A governed retrieval pipeline over synthetic insurance documents that answers questions
like *"Does water damage caused by flooding fall under policy HOME-002?"* with an answer,
clause-level citations, and an explicit "insufficient evidence" path.

```text
INGEST (K8s Job)                                QUERY (ai-api)
----------------                                --------------
data/*.md -> render PDF -> MinIO (raw)          question + filters
        |                                              |
   parse PDF (pypdf)                             embed (LiteLLM -> OpenRouter)
        |                                              |
   structure-aware chunking                      Qdrant hybrid search
   (section/clause, ~400 tokens)                 (dense + sparse, RRF)
        |                                              |
   embed (LiteLLM -> OpenRouter)                 metadata filter
        |                                              |
   Qdrant upsert  +  Postgres registry           rerank (TEI reranker pod)
   (documents, chunks, ingestion_runs)                 |
                                                 grounded prompt -> LLM (Groq)
                                                       |
                                                 answer + citations + chunks
```

Core lesson (from roadmap): **retrieval quality matters more than LLM size**. Stage 2
proves it with numbers: dense-only vs hybrid vs hybrid+rerank on a golden set.

## 2. Scope

In scope:

- Synthetic corpus: 3 policies (motor, home, commercial), 2 procedures, 1 regulation,
  plus 1-2 endorsements that override base wording (deliberate retrieval traps).
- Ingestion pipeline: parse, chunk, embed, upsert; idempotent via content hash.
- Document registry + lineage in Postgres.
- Retrieval: dense baseline -> hybrid (dense + BM25 sparse) -> reranking.
- Metadata filtering: `doc_type`, `product`, `policy_id`, `effective_date`.
- `POST /v1/rag/query` endpoint returning answer, citations, retrieved chunks, scores.
- Evaluation harness + comparison report.
- OTEL spans per RAG step.
- Persistent volumes for Postgres, Qdrant, MinIO (ingested data must survive restarts).

Out of scope (later stages):

- UI / claims copilot (Stage 3)
- Tool calling, claim/policy APIs (Stage 4)
- Real document ACL enforcement - metadata field `acl` added now, enforced later
- GraphRAG, OCR, image documents
- LangChain / LlamaIndex - plain Python first, per roadmap principle

## 3. Proposed decisions (review these)

| # | Decision | Proposal | Alternatives | ADR |
|---|----------|----------|--------------|-----|
| D1 | Vector store | **Qdrant - accepted** (native sparse+dense hybrid, payload filters, Query API fusion) | pgvector (one fewer system, weaker hybrid), OpenSearch (strong BM25, heavy on laptop) | ADR-002 |
| D2 | Embeddings | **Accepted: OpenRouter** `openai/text-embedding-3-small` (1536d) via LiteLLM alias `embed-small` | TEI in-cluster; fastembed in-process. Groq has no embeddings API. | ADR-003 |
| D3 | Reranker | **Accepted: separate pod** - TEI CPU serving `BAAI/bge-reranker-base`, service `reranker` | fastembed cross-encoder in-process; hosted Cohere/Jina; skip | ADR-003 |
| D4 | Sparse / keyword | Qdrant sparse vectors with BM25 via `fastembed` in ingestion + query | Postgres full-text + app-side fusion | ADR-002 |
| D5 | Chunking | Structure-aware: split on headings/clause numbers, cap ~400 tokens, 15% overlap only on oversized sections; keep `section`, `clause`, `page` | Fixed-size token windows (baseline for comparison) | ADR-004 |
| D6 | Corpus format | Author Markdown in `data/`, render to PDF via `reportlab` script so pipeline exercises real PDF parsing | Ingest Markdown directly | ADR-004 |
| D7 | Code layout | New top-level `rag/` Python package (ingestion + retrieval), shared by ai-api and ingest Job; ai-api image build context moves to repo root | Duplicate code inside `apps/ai-api` | - |
| D8 | Ingestion runtime | CLI (`python -m rag.ingestion`) run as K8s **Job**; same image as ai-api | Upload endpoint `POST /v1/documents` (defer to Stage 3) | - |
| D9 | Eval judge | **Accepted:** script-checked metrics always; optional faithfulness judge on a different model family via OpenRouter (`--judge`), cached | Groq judge (self-grading bias); manual only | - |

## 4. Data model

Qdrant collection `insurance_docs`:

- vectors: `dense` (1536, cosine) in 2.2; add `sparse` (BM25) in 2.4
- payload: `doc_id`, `doc_type`, `product`, `policy_id`, `section`, `clause`, `page`,
  `version`, `effective_date`, `acl`, `content_hash`, `text`

Postgres schema `rag`:

- `documents(id, title, doc_type, product, policy_id, version, effective_date, object_key, content_hash, created_at)`
- `chunks(id, document_id, ordinal, section, clause, page, token_count, content_hash)`
- `ingestion_runs(id, started_at, finished_at, status, docs_seen, docs_changed, chunks_written, error)`

MinIO bucket `documents/` - raw PDFs keyed by `doc_type/doc_id/version.pdf`.

## 5. API contract (Phase 2.3)

```http
POST /v1/rag/query
{
  "question": "Is flood damage to the ground floor covered?",
     "policy_id": "HOME-002",
     "loss_date": "2025-03-01",
     "guidance_as_of": "2026-01-01",
  "top_k": 5,
     "mode": "dense"
}

200
{
     "answer": "... [C1]",
  "status": "answered",            # answered | insufficient_evidence
     "citations": [{"ref": "C1", "chunk_id": "...", "doc_id": "POL-HOME-002-v2", "section": "4", "clause": "4.2", "page": 3}],
     "chunks": [{"chunk_id": "...", "ref": "C1", "score": 0.82, "text": "..."}],
  "model": "gpt-oss-20b",
  "latency_ms": 1840,
  "trace_id": "..."
}
```

Guardrails: answer only from supplied context; every claim must cite retrieved chunk refs; the API
validates each ref and renders canonical citations. No usable hits, explicit model abstention, or
invalid citation output yields `insufficient_evidence`. Do not use a dense-score threshold until
Phase 2.5 evaluation calibrates one. Upstream failures return sanitized service errors.

## 6. Build phases

| Phase | Deliverable | Exit check |
|-------|-------------|-----------|
| 2.0 Platform prep | PVCs for data services; TEI reranker Deployment; LiteLLM `embed-small` -> OpenRouter; ADR-002/003/004 | `litellm/embeddings` returns 1536-dim vector; `reranker/rerank` returns scores; data survives pod delete |
| 2.1 Corpus | `data/` Markdown corpus + `scripts/render_corpus.py` -> PDFs and metadata manifest | Complete: 8 PDFs, validated front matter, metadata/hash manifest, deterministic rerender; 6 focused tests passed |
| 2.2 Ingestion | `rag/ingestion` validates manifest, parses/chunks PDFs, embeds through LiteLLM, stores raw PDFs in MinIO, registers lineage in Postgres, and upserts dense vectors to Qdrant; Kubernetes Job | Complete: 8 documents/44 chunks registered; 44 Qdrant points and 8 MinIO objects; dedicated-role rerun completed with zero changes/writes |
| 2.3 Dense RAG | Temporal source selection, dense search, grounded generation, validated inline citations; `/v1/rag/query` | Live smoke query returns cited answer; unit tests verify no-evidence abstention |
| 2.4 Hybrid + rerank | Sparse BM25 vectors, native Qdrant RRF fusion, shared metadata filters, TEI reranking, and backward-compatible API modes | Deployed; 44 points verified with dense+sparse vectors and ingestion no-op verified. Close after bounded-generation fix passes top_k=20 tests; see tracked follow-up below |
| 2.5 Evaluation | `tests/evaluation/golden.yaml` (35 Qs, 105 API attempts), `scripts/run_rag_eval.py`, report in `docs/eval/` | Complete: all 105 requests succeeded; comparative metrics and per-case outcomes recorded; top_k=20 issue remains tracked separately |
| 2.6 Observability + docs | spans `rag.embed`, `rag.search`, `rag.rerank`, `rag.generate` with attributes; smoke test extended; README + stage doc | Trace shows full RAG path; `smoke-test.sh` covers RAG |

Testing: unit tests for chunker, payload builder, source-date selection, prompt assembly, citation
validation, and abstention behavior (pytest, target 80% on new `rag/retrieval/` code); opt-in
read-only integration test against the running cluster.

### Phase 2.2 implementation contract

- **Input and packaging:** Bundle `data/generated/*.pdf` and `manifest.json` into the shared
     ai-api image. The Job reads that immutable input; corpus changes require rebuilding the image.
     Validate manifest schema, unique document IDs, safe relative PDF paths, file presence, and
     each PDF SHA-256 before making service writes. Preserve source and PDF hashes from the manifest.
- **Parsing and chunking:** Extract text in physical page order with `pypdf`; page numbers are
     one-based. Detect headings and clause identifiers using the consistent corpus numbering
     described in ADR-004. Target at most 400 `cl100k_base` tokens per chunk; split only oversized
     clauses and overlap adjacent pieces by 60 tokens (15%). A chunk's `page` is the one-based page
     on which its first text begins. Empty or malformed PDFs fail the run rather than being skipped.
- **Identity and reruns:** Use deterministic document IDs from manifest `doc_id` and deterministic
     chunk IDs from document ID plus ordinal. Compute a document fingerprint from canonical metadata,
     source/PDF hashes, parser/chunker revision, tokenizer identity, embedding alias, and vector
     schema revision. Persist the fingerprint and embedding model identity. An unchanged document is
     a no-op only when its registered chunk IDs and Qdrant point IDs agree; otherwise repair missing
     points. A changed document upserts its desired points, removes stale point IDs for that document,
     and replaces its Postgres chunk registry. Manifest omissions never trigger deletion.
- **Stores and schema:** Apply `rag/sql/001_rag_schema.sql` as the PostgreSQL administrator
     through `scripts/provision-rag-ingest-role.sh`; the Job runtime role receives DML only on the
     `rag` tables and does not run schema DDL. Ensure Qdrant `insurance_docs` exists with named vector `dense`
     (1536, cosine); sparse vectors and BM25 generation are deferred to 2.4. Upload source PDFs to
     the planned `documents/{doc_type}/{doc_id}/{version}.pdf` object key and store that key in the
     registry. Use deterministic Qdrant point IDs and payloads containing document metadata, chunk
     text, section, clause, page, fingerprint, and token count.
- **Retry and concurrency:** Acquire a PostgreSQL advisory lock for the ingestion run. Validate,
     parse, chunk, and embed before writing. Perform idempotent MinIO upload, Qdrant upsert/stale-point
     cleanup, then commit document/chunk state and successful run status in a Postgres transaction.
     Record failed runs and sanitized error categories. A retry converges from any partial store
     failure; no distributed transaction is assumed. Database metadata does not claim completion
     until Qdrant has the desired point set.
- **Embedding and tracing:** Call only LiteLLM `/embeddings` with alias `embed-small` and bearer
     master key; require exactly one 1536-dimensional vector per chunk. Add `rag.ingest`,
     `rag.parse`, `rag.chunk`, `rag.embed`, and `rag.store` spans. Record model alias, counts,
     duration, and non-sensitive document IDs/fingerprints; never record secrets or document text.
- **Runtime and dependencies:** Expose `python -m rag.ingestion`; build the existing ai-api image
     from the repository root and include `rag/`, generated PDFs/manifest, and pinned parser/tokenizer
     dependencies. Register a Kubernetes Job in Kustomize, use `stage1-secrets` only for existing
     service credentials and `rag-ingest-secrets` for the dedicated database password,
     bounded retries/deadline, resource requests/limits, non-root/read-only-root settings, and `/tmp`
     `emptyDir` as needed.
- **Tests:** Unit tests cover manifest validation and path safety, PDF extraction/page numbers,
     clause chunking/token caps/overlap, deterministic IDs/fingerprints, embedding contract, payloads,
     no-op/change/missing-input behavior, and injected failures at each storage boundary. Integration
     tests against kind verify document/chunk rows, MinIO objects, Qdrant point IDs/payloads, and a
     second-run no-op; a second run must repair intentionally removed Qdrant points.

Phase 2.2 excludes query/retrieval and answer generation (2.3), sparse/BM25 and reranking (2.4),
evaluation (2.5), and retrieval observability/reporting beyond ingestion spans (2.6).

Execution record (2026-10-03): the first live run reported `docs_seen=8`, `docs_changed=8`,
`chunks_written=44`; subsequent unchanged runs reported `docs_seen=8`, `docs_changed=0`,
`chunks_written=0`. The latest Job completed 1/1 using `POSTGRES_USER=rag_ingest` and the
isolated `rag-ingest-secrets` Secret. Postgres contains 8 documents and 44 chunks, Qdrant has
44 points, and MinIO has 8 PDF objects. The PostgreSQL administrator owns schema `rag` and its
tables; the ingestion runtime role has explicit column/table grants. Phase 2.3 is complete; see
ADR-009 for query-time source selection, citations, abstention, and read-only access.

### Phase 2.3 implementation contract

- **Request:** `POST /v1/rag/query` accepts a non-empty question, `policy_id`, required
     `loss_date`, optional `guidance_as_of` (defaults to `loss_date`), `top_k` from 1 to 20
     (default 5), and fixed `mode: dense`. Other modes are rejected until Phase 2.4.
- **Source selection:** select the latest base policy effective on or before `loss_date`, plus
     matching endorsements effective by that date. Include relevant policy-specific or global
     procedures/regulations effective by `guidance_as_of`, matching the selected product or `all`.
     Fail closed for no applicable base wording or ambiguous latest versions. The current schema has
     no end-date/supersedes fields; do not infer legal precedence.
- **Least privilege:** API health and source metadata queries use dedicated `rag_query` credentials
     from `rag-query-secrets`. Grant SELECT only on required metadata columns of `rag.documents`;
     never expose bootstrap or ingestion DB credentials to the API.
- **Retrieval:** embed with LiteLLM alias `embed-small`, require a finite 1536-dimension vector,
     and query Qdrant collection `insurance_docs` using named vector `dense`, filtered by the resolved
     document IDs. Preserve scores and citation metadata. Query path does not write to Postgres,
     Qdrant, or MinIO.
- **Grounded response:** send bounded context to LiteLLM `gpt-oss-20b` as untrusted evidence.
     Require structured claims with inline refs such as `[C1]`; validate each ref against retrieved
     chunks; cap output at 800 completion tokens, 20 claims, and 2,000 characters per claim; map refs
     to canonical document/section/clause/page citations. No usable hits, explicit
     model abstention, or invalid citations returns `insufficient_evidence` with an empty answer.
     Do not use an uncalibrated similarity threshold. Infrastructure failures return sanitized errors.
- **Tracing and tests:** add spans for source resolution, `rag.embed`, `rag.search`, and
     `rag.generate` without recording secrets, full questions, or chunk text. Unit-test date/version
     selection, Qdrant filters, prompt/citation validation, abstention, malformed output, and sanitized
     failures. The opt-in cluster test verifies citation-to-chunk mapping and unchanged Postgres
     document/Qdrant point counts.

Phase 2.3 execution record (2026-10-03): the user reports that the dedicated `rag_query` password
was set, the API image was rebuilt and deployed, the service was port-forwarded, and the smoke test
completed successfully with a cited query response. The assistant did not independently repeat the
live query. Dense RAG is complete; Phase 2.4 hybrid retrieval and reranking is deployed, with the
top_k=20 generation follow-up tracked below.

### Phase 2.4 implementation contract

- **Sparse representation:** use FastEmbed `Qdrant/bm25` with separate passage/query encoding.
     Store each chunk as named `dense` plus named `sparse` vectors in `insurance_docs`. Include the
     sparse model identity and vector-schema revision in the ingestion fingerprint so existing
     dense-only registry entries are rebuilt rather than incorrectly treated as no-ops.
- **Qdrant upgrade:** named vectors can be added to an existing collection starting with Qdrant
     1.18. The cluster currently has 1.15.4, so take and download a collection snapshot, then run
     `QDRANT_SNAPSHOT_CONFIRMED=1 ./scripts/upgrade-qdrant.sh`. It upgrades through 1.16.3, 1.17.1,
     1.18.3, and 1.19.1; this avoids the unsupported direct 1.15-to-1.17 storage jump. The
     collection snapshot must be downloaded before the helper runs. The Python client is pinned
     to 1.19.1 to match the final server.
- **Migration and idempotency:** use Qdrant's create-named-vector operation to add sparse config
     in place; never delete/recreate the collection. Rerun the normal ingestion Job over all 8 documents
     and 44 chunks, preserving deterministic point IDs and dense vectors' model. Verify the first
     run repairs every point with both vectors and the second run is a no-op. Ingestion writes both
     named vectors atomically per point; a partial request failure is retried through the existing
     reconciliation path.
- **Hybrid retrieval:** support `dense`, `hybrid`, and `hybrid_rerank` request modes; default to
     `dense` for compatibility. Apply the resolved eligible-document filter to both dense and
     sparse Qdrant prefetches. Fuse ranks using Qdrant's equal-weight RRF; do not tune weights or
     introduce score thresholds before Phase 2.5 evaluation.
- **Candidate bounds:** `top_k` remains the number of chunks returned (1-20). Hybrid prefetches
     use `candidate_k = min(50, max(20, 4 * top_k))`; `hybrid` returns its top `top_k` fused points,
     while `hybrid_rerank` fuses and reranks at most `candidate_k`, then returns top `top_k`.
- **Reranking:** call the existing TEI `reranker:8080/rerank` service only for
     `hybrid_rerank`. Sort its indexed scores explicitly and validate the response shape, indices,
     and finite scores. A TEI outage or malformed response returns a sanitized dependency error;
     never silently return hybrid results under the reranked mode.
- **Response compatibility:** include the effective `mode`, preserve the existing `score` field
     as the final mode-specific ranking score, and add optional `dense_score`, `hybrid_score`, and
     `rerank_score` fields. Dense results expose `dense_score`; hybrid results expose the Qdrant
     fused `hybrid_score`; reranked results retain `hybrid_score` and expose `rerank_score` as the
     final `score`. Qdrant's fused response does not expose each prefetch's raw component score;
     do not issue duplicate searches just to manufacture those fields.
- **Grounding and tracing:** generate from the final ordered result list, assign citation refs in
     that order, and retain the existing citation validation/abstention behavior. Add spans for
     sparse query encoding and `rag.rerank`; record mode, model, candidate/result counts, scores,
     and latency, but no raw question or chunk text.
- **Generation 502 follow-up (2026-10-04):** the live `hybrid` smoke returned an answer at
     `top_k=8`, while the diagnostic `top_k=20` request returned HTTP 502. LiteLLM logs show Groq
     `json_validate_failed` and empty `failed_generation`; the 800-token completion cap is not
     proven to be the cause. ADR-010 now records the remediation decision: keep retrieval/response
     `top_k` as requested, initially generate from the first 8 whole ranked chunks, and retry once
     with 4 chunks only for that specific Groq JSON-validation error. Preserve 800 completion
     tokens and the existing sanitized 502 behavior after a failed retry. Do not relabel an
     upstream failure as insufficient evidence.
- **Tests and exit:** unit-test sparse encoding conversion, in-place schema update, dual-vector
     upsert, fingerprint migration, no-op rerun, filtered RRF, candidate bounds, reranker ordering,
     malformed/upstream failures, and citation mapping. Add tests proving `top_k=20` returns up to
     20 chunks while generation uses bounded evidence, only the allowlisted error retries once,
     and citations remain within the supplied evidence. Run integration checks against the running
     cluster: reingest, verify 44 Qdrant points remain and all carry both named vectors, then smoke
     all three modes including `hybrid` at `top_k=20`. Phase 2.4 demonstrates working behavior only;
     Phase 2.5 owns comparative quality claims and RRF tuning.

### Phase 2.4 outstanding closure item

Observed 2026-10-04: the deployed Qdrant `1.19.1` collection has 44 points, all with valid dense
and populated sparse vectors; Postgres has 8 documents/44 chunks; the latest ingestion rerun was a
no-op. The live API returned cited answers for dense and hybrid-rerank at `top_k=5`. Hybrid
returned `insufficient_evidence` at `top_k=5` and a cited answer at `top_k=8`. A hybrid
`top_k=20` diagnostic returned HTTP 502. LiteLLM logs identify Groq `json_validate_failed` with
empty `failed_generation`; they do not prove that the 800-token completion limit caused it.

Required before declaring Phase 2.4 closed or claiming unrestricted `top_k` support:

1. Keep request `top_k` controlling retrieval and response size, but pass only the highest-ranked
      8 whole chunks to initial generation. Return the full retrieved chunk list unchanged.
2. Retry once with the top 4 whole chunks only when the allowlisted Groq error code is
      `json_validate_failed`; do not retry unrelated errors or malformed successful responses.
3. Preserve the 800 completion-token cap and sanitized 502 after a failed retry. Do not convert a
      provider failure into `insufficient_evidence`, which remains reserved for a successful model
      abstention, no usable evidence, or invalid citations.
4. Test top_k=20 response size, 8-to-4 retry, retry restrictions, and citation mapping. Then
      smoke top_k=20 through the deployed hybrid endpoint and confirm the error no longer occurs.

This item does not block Phase 2.5's fixed top_k=5 baseline evaluation. Report provider failures
separately from answerability/abstention results, and keep this follow-up visible until closed.

### Phase 2.5 evaluation plan

- **Evaluation contract (agreed 2026-10-04):** run through the deployed `/v1/rag/query` HTTP API
     so measurements include the real service path. The runner is read-only and calls no model
     provider directly. Use the same query and temporal filters for `dense`, `hybrid`, and
     `hybrid_rerank`, with `top_k=5`; retain equal-weight RRF. `top_k=8` probes are diagnostics,
     not part of the primary comparison.
- **Golden set:** `tests/evaluation/golden.yaml` contains 35 synthetic questions covering home,
     motor, and commercial policies; endorsements; procedures/regulatory guidance; effective-date
     boundaries; exact identifiers and lexical traps; and unanswerable cases. Each case records a
     stable case ID, question, policy/date inputs, answerability label, and expected relevant chunk
     IDs plus expected document/section/clause locations. Its SHA-256 pins it to the generated corpus
     manifest; before making API calls, the runner recomputes chunk IDs and locations from the
     checked-in PDFs and rejects unknown IDs or labels that disagree with their annotated source
     locations. Dataset validation rejects duplicate IDs, empty relevant evidence for answerable
     cases, and malformed request inputs.
     Annotation audit (2026-10-04): every answerable case's expected IDs were checked against the
     extracted chunk text and source/section/clause metadata; unanswerable labels were checked against
     the checked-in corpus. Unit tests validate every ID-to-location mapping and specifically guard
     the escape-of-water versus gradual-seepage clause boundary.
- **Answer scoring scope:** the baseline scores answerability/status against the gold label and
     citation relevance against expected chunk IDs. It does not claim semantic answer correctness
     or faithfulness; no LLM judge is in this baseline. A later judge or required-fact score needs a
     separately reviewed protocol and must not replace these deterministic measures.
- **Metrics:** recall@5 and MRR are macro-averaged over answerable cases only. Citation precision
     is pooled relevant cited chunks divided by all cited chunks; zero-citation responses have no
     precision value and are counted separately. Answerability accuracy compares
     `answered`/`insufficient_evidence` with the gold label on successful HTTP responses.
     Client-observed latency includes all attempts; service `latency_ms` is available only on
     successful responses. Report median and nearest-rank p95, sample counts, and request failure
     rate over all attempts. HTTP/model failures are neither abstentions nor silently excluded;
     report them by mode and retain status/code and trace ID when available.
- **Execution and provenance:** attempt every case once in each mode, sequentially, with mode order
     rotated deterministically across cases to reduce fixed ordering effects. Do not automatically
     retry failed requests. Record timestamp, dataset/corpus hashes, code revision and evaluator
     source digest, dependency/Python versions, observed generation model, request counts, and
     per-case metrics. Embedding and reranker model configuration is not exposed by this API and is
     explicitly reported as unavailable unless separately verified. Never include credentials or
     generated answer/evidence text. The public response does not expose token usage; do not expand
     the API solely for evaluation.
- **Implementation and report:** `scripts/run_rag_eval.py` accepts API base URL, golden-set path,
     report/results paths, and timeout. Outputs inside the repository are restricted to `docs/eval/`;
     the runner rejects credentials/query secrets, stores only URL origin plus a base-path hash, and
     rejects nested, directory, and source/input collisions before API calls. Keep the golden YAML
     and its PyYAML-only evaluation dependency under `tests/evaluation/`. Unit-test dataset validation,
     metric calculations, failure classification, and response parsing without the cluster. Write
     methodology, environment, per-mode aggregates, per-case outcomes, failures, and limitations to
     `docs/eval/stage2-report.md`, with ID/metric artifacts only and no answer/evidence text.
     Include the API dependency pins plus installed `pypdf`/`tiktoken` versions in provenance because
     PDF parsing and token-based chunk IDs affect gold-label identity.
- **Comparison boundary:** this is a baseline comparison, not an RRF tuning exercise. Do not tune
     fusion weights or introduce score thresholds before reporting baseline results. Any later tuning
     must use a held-out set and report quality, latency, and failure effects for all modes.
- **Phase 2.4 separation:** the known `hybrid` `top_k=20` Groq `json_validate_failed` remains a
     tracked 2.4 closure item. The 2.5 primary comparison uses fixed `top_k=5`; any provider failures
     encountered at that setting are reported separately and still count against request reliability.
     Phase 2.5 may proceed without claiming unrestricted `top_k` support.
- **Exit:** publish a report after every golden case has an attempted request in all three modes,
     metrics and failures are accounted for, and methodology/limitations are explicit. Support quality
     claims only with measured results. Phase 2.5 can proceed while the Phase 2.4 `top_k=20`
     remediation remains tracked.

Execution record (2026-10-04): `docs/eval/stage2-report.md` records all 35 golden cases across
`dense`, `hybrid`, and `hybrid_rerank` at `top_k=5`; 105/105 requests succeeded. Recall@5 was
0.966/0.983/1.000, MRR was 0.931/0.948/0.948, and pooled citation precision was 76.1%/79.5%/78.7%
respectively. Answerability accuracy was 100% for each mode. This does not establish semantic answer
correctness or faithfulness. Phase 2.5 is complete; Phase 2.6 is next. The Phase 2.4 `top_k=20`
generation follow-up remains open.

## 7. Planned file additions

```text
data/{policies,endorsements,procedures,regulations}/*.md
rag/__init__.py
rag/config.py
rag/ingestion/{__main__.py,parse.py,chunk.py,embed.py,store.py,registry.py}
rag/retrieval/{registry.py,sources.py,search.py,generation.py,answer.py}
rag/sql/001_rag_schema.sql
apps/ai-api/main.py                         # + /v1/rag/query
infrastructure/kubernetes/base/{reranker.yaml,rag-ingest-job.yaml,pvc.yaml}
scripts/{render_corpus.py,ingest.sh,provision-rag-query-role.sh,eval-rag.sh}
tests/{unit,integration,evaluation}/
docs/adr/ADR-00{2,3,4,9}-*.md
docs/eval/stage2-report.md
```

## 8. Risks

- TEI image is on GHCR (`cpu-1.8` verified pullable). Model downloads from Hugging Face on first start; cached on PVC.
- Embeddings now leave the laptop (OpenRouter); corpus is synthetic so acceptable. Re-embedding cost is negligible.
- bge-reranker-base scores are small sigmoid values (e.g. 0.016 for the correct clause); the
  `insufficient_evidence` threshold must be calibrated from eval data, not hardcoded.
- CPU-only laptop: reranker adds ~100-400 ms per query for top-20; acceptable for learning, measured in eval.
- Groq rate limits during eval runs: add retry/backoff and cache LLM-judge results.
- The local Job reuses existing LiteLLM and MinIO credentials; the sample MinIO credentials
     may be root-equivalent. Before using a shared cluster, replace them with scoped gateway and
     bucket identities and restrict service network access.
- `cgr.dev/chainguard/minio:latest` is unpinned; pin digest when adding PVCs.

## 9. Decisions log

All resolved 2026-10-01: Qdrant; OpenRouter embeddings; TEI reranker pod; script metrics +
optional OpenRouter judge; UK FCA ICOBS 8 themes (synthetic paraphrase). Phase 2.3 decisions
recorded 2026-10-03 in ADR-009.
