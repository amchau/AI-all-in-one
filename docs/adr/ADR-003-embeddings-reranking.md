# ADR-003 - Embedding and reranking models

## Status

Accepted (2026-10-01)

## Context

Groq (Stage 1 LLM provider) has no embeddings API. Stage 2 needs embeddings for ingestion and
query, plus a reranker to compare dense vs hybrid vs hybrid+rerank. Laptop is CPU-only.
All model traffic must go through LiteLLM where the API shape allows.

## Options - embeddings

| Criterion | OpenRouter (`openai/text-embedding-3-small`) | TEI in-cluster (`bge-small-en-v1.5`) | fastembed in-process |
|-----------|------|------|------|
| Quality | Strong general-purpose, 1536d | Good, 384d | Same models as TEI |
| Latency | Network round-trip | Local CPU | Local CPU, no hop |
| Operational burden | None (API key) | Extra pod + model download | Bigger app image |
| Via LiteLLM | Yes | Yes | No |
| Cost | Fractions of a cent for corpus | Free (CPU/RAM) | Free |
| Data egress | Yes (synthetic data, acceptable) | No | No |
| Portability | Azure OpenAI / Bedrock Titan / Vertex equivalents | Any K8s | Any |

## Options - reranker

| Criterion | TEI pod (`BAAI/bge-reranker-base`) | fastembed cross-encoder in-process | Hosted (Cohere/Jina) |
|-----------|------|------|------|
| Quality | Good cross-encoder | Similar | Strong |
| Latency | ~100-400 ms for top-20 on CPU | Similar, no hop | Network |
| Ops | Separate pod, independently scalable, 1-2 GB RAM | Couples app to model | API key |
| Portability | Same pattern as GPU model serving later (KServe/vLLM) | - | Vendor lock |

## Decision

- Embeddings: OpenRouter `openai/text-embedding-3-small` via LiteLLM alias `embed-small`.
- Reranker: separate TEI CPU pod serving `BAAI/bge-reranker-base`, Service `reranker:8080`,
  called directly via TEI `/rerank` (LiteLLM rerank route optional later).

## Validation

- Phase 2.0: `embed-small` returns 1536-dim vectors; `/rerank` returns ordered scores.
- Eval: hybrid+rerank vs hybrid on recall@5, MRR and added latency.

## Consequences

- Positive: no embedding pod to run; reranker mirrors a real model-serving tier.
- Negative: embeddings depend on OpenRouter availability; changing embedding model needs full re-index
  (store model name in Qdrant payload and Postgres registry).
- Follow-up: compare a local embedding model in Stage 9/10 for data-residency scenarios.
