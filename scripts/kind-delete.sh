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

if [[ -z "${KIND_EXPERIMENTAL_PROVIDER:-}" ]] && command -v podman >/dev/null 2>&1; then
	export KIND_EXPERIMENTAL_PROVIDER=podman
fi

kind delete cluster --name "${CLUSTER_NAME}"
