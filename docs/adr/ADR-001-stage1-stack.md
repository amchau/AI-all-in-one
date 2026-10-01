# ADR-001 - Stage 1 Local Foundation Stack

## Status

Accepted

## Context

Need a fast local platform on Ubuntu with kind + Podman to begin staged enterprise AI build.

## Decision

Use:

- FastAPI for API entrypoint
- LiteLLM as model gateway
- Qdrant for vector store baseline
- PostgreSQL for relational state baseline
- MinIO for object store baseline
- OpenTelemetry Collector for initial tracing output

## Rationale

- FastAPI gives fast iteration for API + orchestration code.
- LiteLLM decouples application from model provider specifics.
- Qdrant is simple to run in Kubernetes and supports metadata filtering.
- PostgreSQL and MinIO are common enterprise primitives needed for later stages.
- OTEL collector in logging mode provides immediate trace visibility with low setup cost.

## Consequences

Positive:

- Stage 1 can run on laptop with minimal external dependencies.
- Architecture aligns with future stages and cloud portability.

Tradeoffs:

- No persistent volume strategy yet.
- No production authn/authz and no policy enforcement yet.
- Inference depends on Groq API availability and a valid `GROQ_API_KEY`.

## Follow-up ADRs

See ADR index in [ROADMAP.md](../ROADMAP.md): ADR-002 vector store, ADR-003 embeddings/reranking,
ADR-004 chunking, ADR-007 workflow engine, ADR-008 observability expansion.
