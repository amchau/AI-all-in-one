---
applyTo: "infrastructure/**/*.yaml,scripts/**/*.sh"
description: Kubernetes manifest and script conventions for the kind + Podman platform.
---

- Namespace `ai-platform`; add every new manifest to `infrastructure/kubernetes/base/kustomization.yaml`.
- Each container: requests/limits, `allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]`,
  `runAsNonRoot` when supported; `readOnlyRootFilesystem: true` needs an `emptyDir` at `/tmp`.
- Pin image tags; local images use `localhost/<name>:<tag>` + `imagePullPolicy: IfNotPresent`.
- Secrets come only from `stage1-secrets` via `secretKeyRef`; new keys must be added to
  `scripts/deploy-stage1.sh` whitelist and `.env.example`.
- Stateful services use PVCs (kind `standard` StorageClass) once data must persist.
- Scripts: `#!/usr/bin/env bash`, `set -euo pipefail`, Podman-aware kind provider, never echo secrets.
- Validate with `kubectl kustomize infrastructure/kubernetes/base >/dev/null` and `bash -n scripts/*.sh`.
