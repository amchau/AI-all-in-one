# AI All In One - Enterprise AI Decision & Operations Platform

This repository builds an Enterprise AI Decision and Operations Platform, starting with
insurance claims investigation.

Current progress:

- Stage 1 platform foundation is complete.
- Stage 2 document ingestion + RAG is in progress; Phase 2.5 evaluation is complete and Phase 2.6 observability + docs is next. The Phase 2.4 top_k=20 generation follow-up remains open.
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
# For an existing Stage 2 cluster, snapshot and upgrade Qdrant before this deploy.
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

Before Phase 2.4 on an existing cluster, snapshot and download the current Qdrant collection.
Keep this port-forward open in one terminal:

```bash
kubectl -n ai-platform port-forward svc/qdrant 6333:6333
```

Then in another terminal, create and download the snapshot before stepping through the supported
Qdrant upgrades. Do not apply the `v1.19.1` manifest directly to data still on `v1.15.4`.

```bash
set -euo pipefail
snapshot_response="$(curl -fSs -X POST http://127.0.0.1:6333/collections/insurance_docs/snapshots)"
snapshot="$(jq -er '.result.name | select(type == "string" and length > 0)' <<<"${snapshot_response}")"
curl -fSs "http://127.0.0.1:6333/collections/insurance_docs/snapshots/${snapshot}" -o "${HOME}/${snapshot}"
[[ -s "${HOME}/${snapshot}" ]]
QDRANT_SNAPSHOT_CONFIRMED=1 ./scripts/upgrade-qdrant.sh
```

The helper upgrades through `1.16.3`, `1.17.1`, `1.18.3`, then `1.19.1`, waiting for each
rollout. Rebuild the API image and run `deploy-stage1.sh` only after it completes.

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
prints its non-secret summary logs. Re-running ingestion is safe. The smoke test calls `/v1/rag/query`
in dense, hybrid, and hybrid-rerank modes with a sample HOME-002 question.

## Phase 2.5 RAG evaluation

With the API port-forward running, install the evaluation parser alongside the API dependencies and
run the fixed-`top_k=5` comparison:

```bash
./.venv/bin/python -m pip install -r apps/ai-api/requirements.txt -r tests/evaluation/requirements.txt
RAG_API_BASE_URL=http://127.0.0.1:8000 ./.venv/bin/python -m scripts.run_rag_eval
```

This sends 105 requests (35 cases across three modes), uses no automatic retries, and may incur model
provider usage. The runner verifies the golden labels against the checked-in corpus before making
requests. It writes `docs/eval/stage2-report.md` and `docs/eval/stage2-results.json`. Exit code `1`
means one or more requests failed; artifacts are still written and failures remain separate from
insufficient-evidence responses. Exit code `2` means preflight validation failed before requests.
Artifacts record the API origin and a hash of any base path, not the raw path.
The known `top_k=20` generation issue is not exercised by this baseline; see the Phase 2.4 follow-up
in the Stage 2 plan.

7. Inspect traces from collector logs:

```bash
kubectl -n ai-platform logs deploy/otel-collector --tail=200
```

## Current status

- Stage 1: done (smoke test passing with Groq `gpt-oss-20b`)
- Stage 2: in progress - Phase 2.5 evaluation is complete; Phase 2.6 observability + docs is next; known top_k=20 generation follow-up remains before Phase 2.4 closure

Full roadmap: [docs/ROADMAP.md](docs/ROADMAP.md). AI assistant context: [AGENTS.md](AGENTS.md).
