# AGENTS.md - context for AI coding assistants

Canonical instructions for any AI agent (Copilot, Claude, Codex, etc.) working in this repo.
Tool-specific files (`CLAUDE.md`, `.github/copilot-instructions.md`) point here.

## Project

Learning + portfolio build of an **Enterprise AI Decision & Operations Platform** on local
Kubernetes. Built in 10 stages (see [docs/ROADMAP.md](docs/ROADMAP.md)). First business domain:
insurance claims investigation.

- Stage 3 Claims Copilot: **Done** (API/UI deployed locally; unit and browser tests pass; live cited brief and collector trace verified; plan: [docs/03-stage3-claims-copilot-plan.md](docs/03-stage3-claims-copilot-plan.md))
- Stage 4 claims tool-calling workflow: **Done** for the local synthetic learning scope, reviewed and accepted 2026-10-06. API and synthetic claims service are deployed locally; unit/integration checks pass and live RAG evidence has been exercised. Evaluation limitations, including incomplete source-domain coverage in the saved all-domains sample, are recorded in [docs/eval/stage4-claims-agent-report.md](docs/eval/stage4-claims-agent-report.md). Handoff: [docs/04-stage4-handoff.md](docs/04-stage4-handoff.md); plan: [docs/04-stage4-tool-calling-agent-plan.md](docs/04-stage4-tool-calling-agent-plan.md).
- Stage 5 claims risk model: **Done for the approved local synthetic prototype**. XGBoost and a separate inference API are deployed locally; metrics and limitations: [docs/eval/stage5-risk-model-report.md](docs/eval/stage5-risk-model-report.md). No real claims data, fraud determination, claim decision, or production-readiness claim.
- Stage 6 hybrid claims investigation: **Done for the user-reviewed local synthetic scope (2026-10-08)**. Pipe-failure and coherent CL-125 flood scenarios verified retrieval, safe schedule uncertainty, JSON-mode final output, separate risk advice, and correlated traces. This is not a general answer-quality or production-readiness claim. The kind cluster was recreated 2026-10-08 with preserved Stage 6 PVCs restored from the detached control-plane volume; Qdrant has 44 points and the Postgres registry has 8 documents. Original volume and backup remain untouched. No automatic retries. Plan: [docs/06-stage6-hybrid-ai-plan.md](docs/06-stage6-hybrid-ai-plan.md); handoff: [docs/06-stage6-handoff.md](docs/06-stage6-handoff.md); [ADR-013](docs/adr/ADR-013-stage6-hybrid-orchestration.md); results/limits: [docs/eval/stage6-hybrid-ai-report.md](docs/eval/stage6-hybrid-ai-report.md).
- Stage 7 human approval workflow: **Done for the approved local synthetic scope; Postgres selected (2026-10-09)**. API/worker, workflow UI, dedicated `claims_workflow` credentials, and transition/concurrency tests are implemented and deployed locally. Process-restart recovery and narrative privacy gates passed; workflow UUID response serialization was fixed and deployed. One browser-submitted `CL-125` workflow failed with `stage6_dependency_failed` and was not retried; successful live Stage 6 workflow completion remains a deferred follow-up, not a dependency for Stage 8. If Stage 8 integrates specialist agents into the approval workflow, include that integration in its acceptance checks. ADR: [ADR-007](docs/adr/ADR-007-workflow-engine-temporal.md); plan/status: [docs/07-stage7-human-approval-plan.md](docs/07-stage7-human-approval-plan.md). This is independent of completed Stage 6.
- Stage 8 specialist agents: **Deferred until concrete requirements are available**. Do not infer specialist decomposition or workflow integration from Stage 9. Revisit the Stage 7 live Stage 6 workflow smoke only before claiming the full live workflow path is verified.
- Stage 9 AI observability: **Done for the approved local synthetic scope**. Prometheus, Loki, Tempo, and Grafana are deployed cluster-internal; bounded HTTP/AI metrics and allowlisted backend logs are queryable; model-free trace/log canaries passed; offline Stage 2/5 evaluation summaries and the reviewer feedback UI/API are implemented. The feedback role, Secret, and API login are configured. Deferred: feedback note privacy/30-day cleanup confirmation and a decision on aggregate-feedback suppression; aggregate endpoint remains disabled. Retention under load, full-suite coverage, broader privacy/correlation, and resource measurements are unverified; local-path PVC requests are not hard quotas. Local port-forward only; no production-readiness claim. Plan: [docs/09-stage9-ai-observability-plan.md](docs/09-stage9-ai-observability-plan.md); accepted ADR: [ADR-008](docs/adr/ADR-008-observability-stack.md).
- Stage 10 production platform: **Draft plan awaiting user review; no implementation approved**. Do not provision infrastructure or select cloud/platform vendors from roadmap candidates until requirements and ADRs are reviewed. Plan: [docs/10-stage10-production-platform-plan.md](docs/10-stage10-production-platform-plan.md).
- Stage 2 is **done**: the Phase 2.4 `top_k=20` hybrid generation follow-up passed live verification; Phases 2.5 and 2.6 are complete. Results: [docs/02-stage2-rag-plan.md](docs/02-stage2-rag-plan.md).
- Completed: Stage 1 foundation ([docs/01-stage1-foundation.md](docs/01-stage1-foundation.md))

## Working agreement

1. **Plan -> review -> build.** Each stage starts with a plan doc the user approves. Do not
   implement beyond the approved plan; propose amendments instead.
2. **Architectural decisions go in ADRs** (`docs/adr/ADR-NNN-*.md`, template ADR-000). Present
   options + trade-offs; the user makes the call.
3. **Plain Python first.** No LangChain/LlamaIndex/agent frameworks unless an ADR justifies it.
   Mechanics (prompting, retrieval, tool loops) must stay visible.
4. **All LLM and embedding traffic goes through LiteLLM.** Apps never call providers directly.
5. **Every AI step is traced.** New LLM/retrieval/tool/ML steps get an OTEL span with useful
   attributes (model, tokens, top_k, scores, doc ids, latency). Never put secrets or full PII in spans.
6. **Measure, don't assume.** Claims like "hybrid is better" or "multi-agent is worth it" need an
   eval result in `docs/eval/`.
7. Keep `docs/ROADMAP.md` status and ADR index current when a stage or ADR changes.

## Stack (Stage 1 baseline)

| Concern | Choice | Where |
|---------|--------|-------|
| Cluster | kind on Podman (`KIND_EXPERIMENTAL_PROVIDER=podman`), cluster `ai-stage1` | `infrastructure/kind/` |
| Namespace | `ai-platform` | `infrastructure/kubernetes/base/` (kustomize) |
| API | FastAPI `apps/ai-api` + shared `rag/`, `agents/`, and `ml/` contracts | image `localhost/ai-api:stage9.3` |
| LLM gateway | LiteLLM, alias `gpt-oss-20b` -> `groq/openai/gpt-oss-20b` | `litellm-configmap.yaml` |
| Vector DB | Qdrant v1.19.1; named-vector changes use `qdrant-client` v1.19.1 | `qdrant.yaml` |
| Relational | PostgreSQL 16 | `postgres.yaml` |
| Object store | MinIO (`cgr.dev/chainguard/minio`) | `minio.yaml` |
| Tracing | OTEL Collector, `debug` exporter (logs) | `otel-collector*.yaml` |
| Embeddings (S2) | LiteLLM alias `embed-small` -> OpenRouter `openai/text-embedding-3-small` (1536d) | `litellm-configmap.yaml` |
| Reranker (S2) | TEI `cpu-1.8`, `BAAI/bge-reranker-base`, `http://reranker:8080/rerank` | `reranker.yaml` |
| Storage (S2) | PVCs (`standard` local-path) for postgres, qdrant, minio, reranker cache | `pvc.yaml` |

## Commands

```bash
./scripts/kind-create.sh        # create cluster (podman provider)
./scripts/build-ai-api.sh       # build + kind load ai-api image
./scripts/build-claims-service.sh # build + kind load synthetic claims service
./scripts/train-claims-risk-model.sh # evaluate synthetic labels; promote only on passing gates
./scripts/build-claims-risk-service.sh # validate latest promotion; build + kind load inference service
./scripts/deploy-stage1.sh      # .env -> secret stage1-secrets, apply kustomize, wait rollouts
QDRANT_SNAPSHOT_CONFIRMED=1 ./scripts/upgrade-qdrant.sh # staged 1.15 -> 1.19 upgrade after snapshot
./scripts/provision-rag-ingest-role.sh # create least-privilege rag_ingest role/schema ownership
./scripts/provision-rag-query-role.sh  # create read-only rag_query role for Phase 2.3
./scripts/provision-workflow-role.sh # create least-privilege claims_workflow role/schema for Stage 7
./scripts/port-forward.sh       # ai-api on localhost:8000
./scripts/smoke-test.sh         # /healthz + /v1/investigate + /v1/rag/query
./scripts/build-claims-frontend.sh # build + kind load claims frontend image
./scripts/port-forward-claims-frontend.sh # frontend on localhost:4173
./scripts/claims-copilot-smoke.sh # one model-backed Stage 3 request; no retries
./scripts/ingest.sh            # run/re-run Phase 2.2 batch ingestion Job
cd apps/frontend && npm ci && npm run test:coverage && npm run test:e2e
python3 -m pytest -q tests/unit
kubectl -n ai-platform logs deploy/otel-collector --tail=200   # traces
kubectl --context kind-ai-stage1 -n ai-platform apply -f infrastructure/kubernetes/base/claims-risk-service.yaml
kubectl --context kind-ai-stage1 -n ai-platform rollout restart deploy/claims-risk-service
kubectl --context kind-ai-stage1 -n ai-platform rollout status deploy/claims-risk-service
kubectl kustomize infrastructure/kubernetes/base >/dev/null    # validate manifests
bash -n scripts/*.sh && python3 -m py_compile apps/ai-api/main.py apps/claims-service/main.py agents/claims/*.py
```

## Secrets

- Real values live only in `.env` (git-ignored). Template: `.env.example`.
- `deploy-stage1.sh` whitelists keys and builds `stage1-secrets` plus isolated
   `rag-ingest-secrets` and `rag-query-secrets`; add keys to the correct Secret and `.env.example`,
   and reject placeholders.
- `rag-ingest` uses fixed role `rag_ingest` with `POSTGRES_INGEST_PASSWORD` in isolated Secret `rag-ingest-secrets`; run the DBA provisioner, set its password locally, then refresh the Secret.
- Stage 7 persistence uses fixed role `claims_workflow` with `POSTGRES_WORKFLOW_PASSWORD` in isolated Secret `claims-workflow-secrets`; run `scripts/provision-workflow-role.sh`, set its password locally, then refresh the Secret. Never reuse bootstrap or RAG credentials.
- `ai-api` uses fixed read-only role `rag_query` with `POSTGRES_QUERY_PASSWORD` in isolated Secret `rag-query-secrets`; never use bootstrap credentials for query-time metadata reads.
- Never print, log, or echo secret values. Check presence with awk/grep that outputs status only.

## Kubernetes conventions

- Every container: resource requests/limits, `allowPrivilegeEscalation: false`,
  `capabilities.drop: [ALL]`, `runAsNonRoot` where the image supports it.
- `readOnlyRootFilesystem: true` requires an `emptyDir` at `/tmp` (Python tempfile needs it).
- Pin image tags (no `latest` for new images); prefer Docker Hub/quay over GHCR when equivalent.
- Local images: tag `localhost/<name>:<tag>`, `imagePullPolicy: IfNotPresent`, load via `kind load`.
- Shared ai-api image builds from the repository root; the base Kustomize Job is suspended until `scripts/ingest.sh` starts it.

## Known gotchas (learned in Stage 1)

- kind defaults to Docker; scripts force Podman provider.
- Podman tags images as `localhost/...`; manifest must match or kubelet tries Docker Hub.
- OTEL collector >= 0.1xx removed `logging` exporter; use `debug`.
- Postgres needs `fsGroup: 999`; Qdrant needs a writable `/qdrant/snapshots` or storage mount.
- MinIO official images failed to pull (quay 401, GHCR 403); chainguard image works.
- `kubectl port-forward` dies on pod rollout; restart it after `rollout restart`.
- LiteLLM requires `Authorization: Bearer $LITELLM_MASTER_KEY`.
- Groq has no embeddings endpoint; embeddings go to OpenRouter via LiteLLM (`openai/` provider + `api_base`).
- Changing a Deployment strategy to `Recreate` cannot be applied in place; delete and re-apply.
- TEI reranker (fp32 ONNX) OOMs at 2Gi; needs 4Gi limit. Model cached on PVC `reranker-cache`.

## Code style

- Python 3.12, type hints, pydantic models at API boundaries, pydantic-settings for config.
- Every new or modified Python file starts with a concise module docstring stating the file's purpose; inline comments explain non-obvious logic only.
- Small functions, sanitized error responses (no upstream error text to clients), log details server-side.
- Tests: pytest under `tests/{unit,integration,evaluation}`; aim 80% on new packages.
- Commits: conventional (`feat:`, `fix:`, `docs:`, ...).
