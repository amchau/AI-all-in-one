#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="ai-stage1"
CONFIG_FILE="infrastructure/kind/kind-stage1.yaml"

if [[ -z "${KIND_EXPERIMENTAL_PROVIDER:-}" ]] && command -v podman >/dev/null 2>&1; then
  export KIND_EXPERIMENTAL_PROVIDER=podman
fi

if kind get clusters | grep -qx "${CLUSTER_NAME}"; then
  echo "kind cluster ${CLUSTER_NAME} already exists"
  exit 0
fi

kind create cluster --name "${CLUSTER_NAME}" --config "${CONFIG_FILE}"
kubectl cluster-info --context "kind-${CLUSTER_NAME}"
