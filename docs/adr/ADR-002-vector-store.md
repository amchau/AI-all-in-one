# ADR-002 - Vector store

## Status

Accepted (2026-10-01)

## Context

Stage 2 needs dense + keyword (hybrid) retrieval with metadata filters (`policy_id`, `doc_type`,
`effective_date`) over a small corpus on a laptop kind cluster, with a path to production scale.

## Options

| Criterion | Qdrant | pgvector | OpenSearch |
|-----------|--------|----------|------------|
| Scale | Millions+ vectors, sharding | Fine to ~10M with HNSW; tied to PG sizing | Large scale, mature sharding |
| Latency | Low; HNSW + payload index | Low-moderate; planner-dependent with filters | Moderate; JVM |
| Hybrid / filtering | Native sparse + dense, server-side RRF/DBSF fusion, payload filters | Dense only; keyword via PG full-text + app-side fusion | Best-in-class BM25 + kNN, hybrid pipelines |
| Operational burden (laptop) | Single small pod | None extra (already run Postgres) | Heavy (2-4 GB heap) |
| Kubernetes support | Official Helm chart, operator (cloud) | Any PG operator | Operator, Helm |
| Cost | OSS; managed Qdrant Cloud | OSS; managed via any PG service | OSS; managed AWS OpenSearch |
| Developer experience | Simple REST/gRPC, Python client | SQL, one system | Verbose DSL |
| Cloud portability | Qdrant Cloud, self-host anywhere | Azure PG Flexible, RDS, Cloud SQL, AlloyDB | AWS OpenSearch; Azure AI Search / Vertex as analogues |

## Decision

Qdrant. Native hybrid (sparse BM25 + dense) and server-side fusion keep retrieval mechanics
in one query, and it already runs from Stage 1.

## Validation

Stage 2 eval (`docs/eval/stage2-report.md`): hybrid must beat dense-only on recall@5/MRR;
p95 search latency < 100 ms on laptop.

## Consequences

- Positive: one query for hybrid + filters; lightweight pod.
- Negative: second datastore beside Postgres; registry/lineage must stay consistent across both.
- Follow-up: revisit pgvector if operational simplicity outweighs hybrid quality in eval.
