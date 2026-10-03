#!/usr/bin/env bash
set -euo pipefail

if ! command -v flock >/dev/null 2>&1; then
  echo "flock is required to serialize platform operations"
  exit 1
fi
LOCK_DIR="${XDG_RUNTIME_DIR:-${HOME}/.cache}/ai-all-in-one"
mkdir -p "${LOCK_DIR}"
chmod 700 "${LOCK_DIR}"
LOCK_FILE="${LOCK_DIR}/kind-ai-stage1.lock"
exec 9>>"${LOCK_FILE}"
chmod 600 "${LOCK_FILE}"
if ! flock -n 9; then
  echo "another platform operation is already running"
  exit 1
fi

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
