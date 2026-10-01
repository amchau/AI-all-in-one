# AGENTS.md - context for AI coding assistants

Canonical instructions for any AI agent (Copilot, Claude, Codex, etc.) working in this repo.
Tool-specific files (`CLAUDE.md`, `.github/copilot-instructions.md`) point here.

## Project

Learning + portfolio build of an **Enterprise AI Decision & Operations Platform** on local
Kubernetes. Built in 10 stages (see [docs/ROADMAP.md](docs/ROADMAP.md)). First business domain:
insurance claims investigation.

- Current stage: **2 - Document ingestion + RAG** (plan: [docs/02-stage2-rag-plan.md](docs/02-stage2-rag-plan.md))
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
| API | FastAPI `apps/ai-api` | image `localhost/ai-api:stage1` |
| LLM gateway | LiteLLM, alias `gpt-oss-20b` -> `groq/openai/gpt-oss-20b` | `litellm-configmap.yaml` |
| Vector DB | Qdrant v1.15.4 | `qdrant.yaml` |
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
./scripts/deploy-stage1.sh      # .env -> secret stage1-secrets, apply kustomize, wait rollouts
./scripts/port-forward.sh       # ai-api on localhost:8000
./scripts/smoke-test.sh         # /healthz + /v1/investigate
kubectl -n ai-platform logs deploy/otel-collector --tail=200   # traces
kubectl kustomize infrastructure/kubernetes/base >/dev/null    # validate manifests
bash -n scripts/*.sh && python3 -m py_compile apps/ai-api/main.py
```

## Secrets

- Real values live only in `.env` (git-ignored). Template: `.env.example`.
- `deploy-stage1.sh` whitelists keys and builds secret `stage1-secrets`; add new keys there
  and in `.env.example`, and reject placeholders with `assert_not_placeholder`.
- Never print, log, or echo secret values. Check presence with awk/grep that outputs status only.

## Kubernetes conventions

- Every container: resource requests/limits, `allowPrivilegeEscalation: false`,
  `capabilities.drop: [ALL]`, `runAsNonRoot` where the image supports it.
- `readOnlyRootFilesystem: true` requires an `emptyDir` at `/tmp` (Python tempfile needs it).
- Pin image tags (no `latest` for new images); prefer Docker Hub/quay over GHCR when equivalent.
- Local images: tag `localhost/<name>:<tag>`, `imagePullPolicy: IfNotPresent`, load via `kind load`.

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
- Small functions, sanitized error responses (no upstream error text to clients), log details server-side.
- Tests: pytest under `tests/{unit,integration,evaluation}`; aim 80% on new packages.
- Commits: conventional (`feat:`, `fix:`, `docs:`, ...).
