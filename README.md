# AI All In One - Enterprise AI Decision & Operations Platform

This repository builds an Enterprise AI Decision and Operations Platform, starting with
insurance claims investigation.

Current progress:

- Stage 1 platform foundation is complete.
- Stage 2 document ingestion + RAG is in progress; Phases 2.0-2.3 are complete and Phase 2.4 hybrid retrieval is next.
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
registered but suspended during normal deployment. On a fresh database, the script defers only
the API readiness wait while `rag_query` is absent; the API becomes ready after the query role and
schema grants are provisioned.

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

Phase 2.3 also needs a read-only API metadata role. Provision it and set its password separately:

```bash
./scripts/provision-rag-query-role.sh
```

At the `psql` prompt, run `\password rag_query`; use that value for `POSTGRES_QUERY_PASSWORD` in
`.env`. Re-run `./scripts/deploy-stage1.sh` to update `rag-query-secrets`. The API uses this
read-only identity for both Postgres readiness and policy-version selection; deployment restarts
the API so updated credentials take effect.

4. After provisioning both roles and refreshing secrets, run ingestion before the RAG smoke test:

```bash
./scripts/ingest.sh
```

5. Port-forward API:

```bash
./scripts/port-forward.sh
```

6. In another terminal, run smoke test:

```bash
./scripts/smoke-test.sh
```

The ingestion script recreates and starts the suspended Job, watches for success or failure, and
prints its non-secret summary logs. Re-running ingestion is safe. The smoke test calls the dense
`/v1/rag/query` endpoint with a sample HOME-002 question.

7. Inspect traces from collector logs:

```bash
kubectl -n ai-platform logs deploy/otel-collector --tail=200
```

## Current status

- Stage 1: done (smoke test passing with Groq `gpt-oss-20b`)
- Stage 2: in progress - phases 2.0 through 2.3 complete; Phase 2.4 hybrid retrieval and reranking next

Full roadmap: [docs/ROADMAP.md](docs/ROADMAP.md). AI assistant context: [AGENTS.md](AGENTS.md).
