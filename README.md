# AI All In One - Enterprise AI Decision & Operations Platform

This repository builds an Enterprise AI Decision and Operations Platform, starting with
insurance claims investigation.

Current progress:

- Stage 1 platform foundation is complete.
- Stage 2 document ingestion + RAG is complete. The Phase 2.4 top_k=20 generation follow-up passed its live hybrid verification on 2026-10-05.
- Stage 3 Claims Copilot is complete. API/UI are deployed locally; automated checks and a live cited brief with collector trace pass.
- Stage 4 bounded claims tool-calling workflow is done for the local synthetic learning scope; API and synthetic claims-service are deployed, live RAG evidence and collector spans were exercised, and unit/integration checks pass. The reviewed evaluation documents model-quality limitations and is not a production-readiness claim. See the [Stage 4 evaluation report](docs/eval/stage4-claims-agent-report.md) and [handoff](docs/04-stage4-handoff.md).
- Stage 5 claims risk model is done for the approved local synthetic prototype. It is advisory, routes uncertain cases to handler triage, and is not a fraud or coverage decision or a production-readiness claim. See the [Stage 5 evaluation report](docs/eval/stage5-risk-model-report.md) and [plan](docs/05-stage5-claims-risk-model-plan.md).
- Stage 6 hybrid claims investigation is done for the user-reviewed local synthetic scope (2026-10-08): pipe and flood scenarios verified retrieval, schedule uncertainty, JSON-mode final output, separate risk advice, and correlated traces. This is not a general answer-quality or production-readiness claim. See the [Stage 6 integration report](docs/eval/stage6-hybrid-ai-report.md), [handoff](docs/06-stage6-handoff.md), [plan](docs/06-stage6-hybrid-ai-plan.md), and [ADR-013](docs/adr/ADR-013-stage6-hybrid-orchestration.md).
- See [docs/ROADMAP.md](docs/ROADMAP.md), [docs/02-stage2-rag-plan.md](docs/02-stage2-rag-plan.md), and [docs/03-stage3-claims-copilot-plan.md](docs/03-stage3-claims-copilot-plan.md).

## Stack

- Kubernetes: kind
- Container runtime: Podman
- API service: FastAPI (`apps/ai-api`)
- Frontend: React + Vite (`apps/frontend`)
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
  claims-service/
  frontend/
agents/
  claims/
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
./scripts/build-claims-frontend.sh
```

3. Create secrets and deploy the platform:

```bash
cp .env.example .env
# set `GROQ_API_KEY` and replace all other `set-me` values
# For an existing Stage 2 cluster, snapshot and upgrade Qdrant before this deploy.
./scripts/deploy-stage1.sh
```

`deploy-stage1.sh` safely parses `.env` and creates/updates Kubernetes secret `stage1-secrets`.
The API build script creates `localhost/ai-api:stage6.0`. The ingestion Job is
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
in dense, hybrid, and hybrid-rerank modes with a sample HOME-002 question. It validates each response
and prints the mode, answer status, and trace ID without printing retrieved evidence. A hybrid response
with `insufficient_evidence` is valid at `top_k=5`.

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

7. Correlate each `trace_id` printed by the smoke test with collector output. For example, replace
`<trace_id>` with one of the printed IDs:

```bash
kubectl -n ai-platform logs deploy/otel-collector --since=10m | grep -F '<trace_id>'
```

Each trace should include `rag.query`, `rag.source_resolution`, `rag.embed`, `rag.search`, and
`rag.generate`; hybrid modes also include `rag.sparse_embed`, and `hybrid_rerank` includes
`rag.rerank`. Span attributes capture bounded operational metadata (such as mode, model, counts, and
scores), not the raw question or evidence text. Collector export is asynchronous, so inspect logs
after the request completes. If the trace ID is missing or no match appears, check API/collector
health and retry the inspection before rerunning the model-backed smoke requests.

## Stage 3 Claims Copilot

The local handler UI uses the existing corpus and fixed `hybrid_rerank`, `top_k=5` retrieval. It
accepts synthetic claim details and shows citation-backed findings for handler review; it does not
make coverage decisions or persist claims. The narrative is sent through LiteLLM to configured
hosted embedding (currently OpenRouter) and generation (currently Groq) providers, so use synthetic
text only and never enter real PII;
provider retention is outside this repository's control.
Stage 2 and its Phase 2.4 `top_k=20` follow-up are now complete. The legacy
cluster-internal `/v1/investigate` endpoint remains for existing callers; the Stage 6 UI uses
`/v1/claims/hybrid-investigations`. Stage 3's RAG-only `/v1/investigations` and Stage 4's separate
synthetic-only `POST /v1/claims/agent-investigations` endpoint remain backward-compatible; Stage 4
performs bounded, read-only tool lookups and
may retrieve policy evidence through the existing RAG service. The endpoint does not make coverage
or fraud determinations and is not an authenticated production interface. Stage 4's API and mock service are now deployed to the local cluster; see the [Stage 4 execution and evaluation report](docs/eval/stage4-claims-agent-report.md) for measured checks and limitations. The Stage 2 `top_k=20` prerequisite passed before integration. To build/load and roll out the synthetic service, run `./scripts/build-claims-service.sh`, then `kubectl --context kind-ai-stage1 apply -f infrastructure/kubernetes/base/claims-service.yaml` and `kubectl --context kind-ai-stage1 -n ai-platform rollout status deploy/claims-service`.


Run the frontend locally against the API port-forward:

```bash
./scripts/port-forward.sh
npm --prefix apps/frontend ci
npm --prefix apps/frontend run dev
```

For the kind deployment, rebuild/load the frontend image, apply only its manifest, and forward its
service:

```bash
./scripts/build-claims-frontend.sh
kubectl --context kind-ai-stage1 apply -f infrastructure/kubernetes/base/claims-frontend.yaml
kubectl --context kind-ai-stage1 -n ai-platform rollout restart deploy/claims-frontend
kubectl --context kind-ai-stage1 -n ai-platform rollout status deploy/claims-frontend
./scripts/port-forward-claims-frontend.sh
```

Open `http://127.0.0.1:4173`. Frontend tests are `npm --prefix apps/frontend run test:coverage`
and `npm --prefix apps/frontend run test:e2e`. The one-shot live check is
`./scripts/claims-copilot-smoke.sh`; it sends one provider-backed request and never retries.

An initial live request returned HTTP 502 because Groq rejected constrained JSON with
`json_validate_failed`. Stage 3 now uses prompt-guided JSON with strict local validation. The final
one-shot HOME-002 request returned a cited brief and its trace correlated with the collector. The smoke script makes one provider-backed request and does not automatically retry. Stage 2's
Phase 2.4 `top_k=20` follow-up has since passed live verification; see the Stage 2 execution record.


## Stage 5 Claims Risk Model

Stage 5 is complete for a synthetic local prototype only. The model estimates whether a synthetic
case should receive human review; it does not detect fraud, decide coverage, or automate claims.
Incomplete or near-threshold assessments are returned for handler triage. Never use real customer or
claim data.

Train/evaluate and promote only if the synthetic holdout gates pass, then build/load the inference
image and apply its internal service manifest:

```bash
./scripts/train-claims-risk-model.sh
./scripts/build-claims-risk-service.sh
kubectl --context kind-ai-stage1 apply -f infrastructure/kubernetes/base/claims-risk-service.yaml
kubectl --context kind-ai-stage1 -n ai-platform rollout restart deploy/claims-risk-service
kubectl --context kind-ai-stage1 -n ai-platform rollout status deploy/claims-risk-service
```

Metrics, provenance, and limitations: [Stage 5 evaluation report](docs/eval/stage5-risk-model-report.md).
Stage 6 consumes this standalone API through deterministic server orchestration. It does not change
Stage 5 features, labels, thresholds, or model semantics.

## Stage 6 Hybrid Claims Investigation

The combined API resolves policy and loss date from the synthetic claim record, performs hybrid RAG
retrieval before the bounded claims agent, and returns risk advice separately. Retrieved policy
chunks enter the agent as validated source-linked context without a separate RAG answer-generation
call. If risk
inference is unavailable, the investigation remains available with an explicit unavailable advisory.
The existing frontend is the primary handler path. This is a local synthetic prototype, not a fraud
determination, claim decision, or production interface. The October 6 smoke predates mandatory
retrieval; the October 7 trace verifies retrieval, agent, and risk spans without an extra RAG answer
generation call. See the [Stage 6 integration report](docs/eval/stage6-hybrid-ai-report.md) for
verification and limitations.

## Current status

- Stage 1: done (smoke test passing with Groq `gpt-oss-20b`)
- Stage 2: done - bounded `top_k=20` hybrid generation passed the documented live exit check; see [docs/02-stage2-rag-plan.md](docs/02-stage2-rag-plan.md)
- Stage 3: done - API/UI deployed; unit/browser checks pass; live cited brief and collector trace verified
- Stage 4: done for the reviewed local synthetic learning scope; see [the evaluation report](docs/eval/stage4-claims-agent-report.md) for limitations, including incomplete payment/fraud source coverage in the saved all-domains case
- Stage 5: done for the approved local synthetic model scope; not real-world risk quality
- Stage 6: done for the reviewed local synthetic scope; limitations remain; see [the integration report](docs/eval/stage6-hybrid-ai-report.md)

Full roadmap: [docs/ROADMAP.md](docs/ROADMAP.md). AI assistant context: [AGENTS.md](AGENTS.md).
