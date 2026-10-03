---
applyTo: "infrastructure/**/*.yaml,scripts/**/*.sh"
description: Kubernetes manifest and script conventions for the kind + Podman platform.
---

- Namespace `ai-platform`; add every new manifest to `infrastructure/kubernetes/base/kustomization.yaml`.
- Each container: requests/limits, `allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]`,
  `runAsNonRoot` when supported; `readOnlyRootFilesystem: true` needs an `emptyDir` at `/tmp`.
- Pin image tags; local images use `localhost/<name>:<tag>` + `imagePullPolicy: IfNotPresent`.
- Use `stage1-secrets` for platform credentials and isolated Secrets for workload-specific
  credentials (`rag-ingest-secrets` for the ingestion DB password). Add keys to
  `scripts/deploy-stage1.sh` and `.env.example`; never expose a workload secret via broad `envFrom`.
- Stateful services use PVCs (kind `standard` StorageClass) once data must persist.
- Scripts: `#!/usr/bin/env bash`, `set -euo pipefail`, Podman-aware kind provider, never echo secrets.
- Validate with `kubectl kustomize infrastructure/kubernetes/base >/dev/null` and `bash -n scripts/*.sh`.
