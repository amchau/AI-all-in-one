#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="ai-stage1"

if [[ -z "${KIND_EXPERIMENTAL_PROVIDER:-}" ]] && command -v podman >/dev/null 2>&1; then
	export KIND_EXPERIMENTAL_PROVIDER=podman
fi

kind delete cluster --name "${CLUSTER_NAME}"
