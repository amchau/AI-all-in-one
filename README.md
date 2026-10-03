# AI All In One - Enterprise AI Decision & Operations Platform

This repository builds an Enterprise AI Decision and Operations Platform, starting with
insurance claims investigation.

Current progress:

- Stage 1 platform foundation is complete.
- Stage 2 document ingestion + RAG is in progress; Phase 2.2 adds an idempotent ingestion Job.
- See [docs/ROADMAP.md](docs/ROADMAP.md) and [docs/02-stage2-rag-plan.md](docs/02-stage2-rag-plan.md).

## Stack

- Kubernetes: kind
- Container runtime: Podman
- API service: FastAPI (`apps/ai-api`)
- LLM gateway: LiteLLM
- Data services: PostgreSQL, Qdrant, MinIO
- Observability: OpenTelemetry Collector (`debug` exporter)
- Ingestion: pypdf, tiktoken, LiteLLM embeddings, Qdrant, PostgreSQL, MinIO

## Prerequisites

- Ubuntu with Podman installed
- kind
- kubectl
- `flock` (util-linux)
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

3. Create secrets and deploy the platform:

```bash
cp .env.example .env
# set `GROQ_API_KEY` and replace all other `set-me` values
./scripts/deploy-stage1.sh
```

`deploy-stage1.sh` safely parses `.env` and creates/updates Kubernetes secret `stage1-secrets`.
The build script creates the shared `localhost/ai-api:stage2` image. The ingestion Job is
registered but suspended during normal deployment.

Before the first Phase 2.2 run, provision the dedicated database role, set its password in
`.env`, and update its isolated Kubernetes secret:

```bash
./scripts/provision-rag-ingest-role.sh
kubectl -n ai-platform exec -it deploy/postgres -- sh -c 'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

The provisioner runs schema migrations as the PostgreSQL administrator and grants the
runtime role only the required schema and table privileges. For this dedicated lab database,
it also removes the default temporary-table privilege from `PUBLIC`. At the `psql` prompt, run
`\password rag_ingest`;
use that same value for `POSTGRES_INGEST_PASSWORD` in `.env`. Then run
`./scripts/deploy-stage1.sh` to update the isolated `rag-ingest-secrets` Secret.

4. Port-forward API:

```bash
./scripts/port-forward.sh
```

5. In another terminal, run smoke test:

```bash
./scripts/smoke-test.sh
```

6. Run the Phase 2.2 ingestion Job when ready:

```bash
./scripts/ingest.sh
```

The script recreates and starts the suspended Job, watches for success or failure, and prints
its non-secret summary logs. Re-running ingestion is safe.

7. Inspect traces from collector logs:

```bash
kubectl -n ai-platform logs deploy/otel-collector --tail=200
```

## Current status

- Stage 1: done (smoke test passing with Groq `gpt-oss-20b`)
- Stage 2: in progress - phases 2.0 through 2.2 complete; Phase 2.3 dense RAG is next

Full roadmap: [docs/ROADMAP.md](docs/ROADMAP.md). AI assistant context: [AGENTS.md](AGENTS.md).
