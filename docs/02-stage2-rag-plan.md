# Stage 2 - Insurance Knowledge System (Enterprise RAG)

Status: **APPROVED 2026-10-01** - phase 2.0 done, next 2.1 (corpus)
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

- vectors: `dense` (1536, cosine), `sparse` (BM25)
- payload: `doc_id`, `doc_type`, `product`, `policy_id`, `section`, `clause`, `page`,
  `version`, `effective_date`, `acl`, `content_hash`, `text`

Postgres schema `rag`:

- `documents(id, title, doc_type, product, policy_id, version, effective_date, object_key, content_hash, created_at)`
- `chunks(id, document_id, ordinal, section, clause, page, token_count, content_hash)`
- `ingestion_runs(id, started_at, finished_at, status, docs_seen, docs_changed, chunks_written, error)`

MinIO bucket `documents/` - raw PDFs keyed by `doc_type/doc_id/version.pdf`.

## 5. API contract (draft)

```http
POST /v1/rag/query
{
  "question": "Is flood damage to the ground floor covered?",
  "filters": {"policy_id": "HOME-002", "doc_type": ["policy", "endorsement"]},
  "top_k": 5,
  "mode": "hybrid_rerank"          # dense | hybrid | hybrid_rerank
}

200
{
  "answer": "...",
  "status": "answered",            # answered | insufficient_evidence
  "citations": [{"doc_id": "HOME-002", "section": "4", "clause": "4.2", "page": 3}],
  "chunks": [{"chunk_id": "...", "score": 0.82, "rerank_score": 0.91, "text": "..."}],
  "model": "gpt-oss-20b",
  "latency_ms": 1840,
  "trace_id": "..."
}
```

Guardrails: answer only from supplied context; every claim must cite a chunk; if top
rerank score < threshold -> `insufficient_evidence` without calling the LLM.

## 6. Build phases

| Phase | Deliverable | Exit check |
|-------|-------------|-----------|
| 2.0 Platform prep | PVCs for data services; TEI reranker Deployment; LiteLLM `embed-small` -> OpenRouter; ADR-002/003/004 | `litellm/embeddings` returns 1536-dim vector; `reranker/rerank` returns scores; data survives pod delete |
| 2.1 Corpus | `data/` Markdown corpus + `scripts/render-corpus.py` -> PDFs | 8-10 PDFs, each with doc metadata front-matter |
| 2.2 Ingestion | `rag/ingestion` parse/chunk/embed/upsert + Postgres registry; K8s Job | Re-run is no-op (idempotent); counts match registry |
| 2.3 Dense RAG | `rag/retrieval` dense search + grounded generation; `/v1/rag/query` mode `dense` | Smoke question returns cited answer |
| 2.4 Hybrid + rerank | sparse vectors, RRF fusion, metadata filters, reranker | Modes `hybrid`, `hybrid_rerank` work |
| 2.5 Evaluation | `tests/evaluation/golden.yaml` (~30 Qs), `run_rag_eval.py`, report in `docs/eval/` | Report compares 3 modes on recall@5, MRR, citation accuracy, latency |
| 2.6 Observability + docs | spans `rag.embed`, `rag.search`, `rag.rerank`, `rag.generate` with attributes; smoke test extended; README + stage doc | Trace shows full RAG path; `smoke-test.sh` covers RAG |

Testing: unit tests for chunker, payload builder, prompt assembly, score thresholding
(pytest, target 80% on `rag/`); integration test against the running cluster.

## 7. Planned file additions

```text
data/{policies,endorsements,procedures,regulations}/*.md
rag/__init__.py
rag/config.py
rag/ingestion/{__main__.py,parse.py,chunk.py,embed.py,store.py,registry.py}
rag/retrieval/{search.py,rerank.py,prompt.py,answer.py}
rag/sql/001_rag_schema.sql
apps/ai-api/main.py                         # + /v1/rag/query
infrastructure/kubernetes/base/{reranker.yaml,rag-ingest-job.yaml,pvc.yaml}
scripts/{render-corpus.py,ingest.sh,eval-rag.sh}
tests/{unit,integration,evaluation}/
docs/adr/ADR-00{2,3,4}-*.md
docs/eval/stage2-report.md
```

## 8. Risks

- TEI image is on GHCR (`cpu-1.8` verified pullable). Model downloads from Hugging Face on first start; cached on PVC.
- Embeddings now leave the laptop (OpenRouter); corpus is synthetic so acceptable. Re-embedding cost is negligible.
- bge-reranker-base scores are small sigmoid values (e.g. 0.016 for the correct clause); the
  `insufficient_evidence` threshold must be calibrated from eval data, not hardcoded.
- CPU-only laptop: reranker adds ~100-400 ms per query for top-20; acceptable for learning, measured in eval.
- Groq rate limits during eval runs: add retry/backoff and cache LLM-judge results.
- `cgr.dev/chainguard/minio:latest` is unpinned; pin digest when adding PVCs.

## 9. Decisions log

All resolved 2026-10-01: Qdrant; OpenRouter embeddings; TEI reranker pod; script metrics +
optional OpenRouter judge; UK FCA ICOBS 8 themes (synthetic paraphrase).
