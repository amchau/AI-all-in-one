# Stage 2 - Insurance Knowledge System (Enterprise RAG)

Status: **IN PROGRESS** - phases 2.0-2.3 complete; Phase 2.4 hybrid retrieval and reranking next
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
| 2.4 Hybrid + rerank | sparse vectors, RRF fusion, metadata filters, reranker | Modes `hybrid`, `hybrid_rerank` work |
| 2.5 Evaluation | `tests/evaluation/golden.yaml` (~30 Qs), `run_rag_eval.py`, report in `docs/eval/` | Report compares 3 modes on recall@5, MRR, citation accuracy, latency |
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
live query. Dense RAG is complete; Phase 2.4 hybrid retrieval and reranking is next.

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
