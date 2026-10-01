# AI All In One - Stage 1 Foundation

This repository starts Stage 1 of the Enterprise AI Decision and Operations Platform.

Stage 1 goal:

- Bring up local platform foundation on kind + Podman.
- Deploy core services: PostgreSQL, Qdrant, MinIO, LiteLLM, FastAPI API, OpenTelemetry Collector.
- Send first request through API -> LiteLLM and capture traces.

## Stack for Stage 1

- Kubernetes: kind
- Container runtime: Podman
- API service: FastAPI (`apps/ai-api`)
- LLM gateway: LiteLLM
- Data services: PostgreSQL, Qdrant, MinIO
- Observability: OpenTelemetry Collector (logging exporter)

## Prerequisites

- Ubuntu with Podman installed
- kind
- kubectl
- docker or podman build support for local image builds
- Groq API key in `.env` for `openai/gpt-oss-20b`

Note: scripts auto-select Podman for kind when available.

## Repo layout

```text
apps/
  ai-api/
docs/
  adr/
infrastructure/
  kind/
  kubernetes/
scripts/
```

## Quick start

1. Create cluster:

```bash
./scripts/kind-create.sh
```

2. Build API image and load into kind:

```bash
./scripts/build-ai-api.sh
```

3. Create LiteLLM secrets and deploy Stage 1:

```bash
cp .env.example .env
# set `GROQ_API_KEY` and replace all other `set-me` values
./scripts/deploy-stage1.sh
```

`deploy-stage1.sh` safely parses `.env` and creates/updates Kubernetes secret `stage1-secrets`.

4. Port-forward API:

```bash
./scripts/port-forward.sh
```

5. In another terminal, run smoke test:

```bash
./scripts/smoke-test.sh
```

6. Inspect traces from collector logs:

```bash
kubectl -n ai-platform logs deploy/otel-collector --tail=200
```

## Current status

- Stage 1: done (smoke test passing with Groq `gpt-oss-20b`)
- Stage 2: planning - see [docs/02-stage2-rag-plan.md](docs/02-stage2-rag-plan.md)

Full roadmap: [docs/ROADMAP.md](docs/ROADMAP.md). AI assistant context: [AGENTS.md](AGENTS.md).
