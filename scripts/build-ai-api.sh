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

IMAGE_NAME="localhost/ai-api:stage9.4"
CLUSTER_NAME="ai-stage1"

if [[ -z "${KIND_EXPERIMENTAL_PROVIDER:-}" ]] && command -v podman >/dev/null 2>&1; then
  export KIND_EXPERIMENTAL_PROVIDER=podman
fi

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  docker build -t "${IMAGE_NAME}" -f apps/ai-api/Dockerfile .
  kind load docker-image "${IMAGE_NAME}" --name "${CLUSTER_NAME}"
elif command -v podman >/dev/null 2>&1; then
  podman build -t "${IMAGE_NAME}" -f apps/ai-api/Dockerfile .
  TMP_ARCHIVE="$(mktemp -t ai-api-image-XXXXXX.tar)"
  trap 'rm -f "${TMP_ARCHIVE}"' EXIT
  podman save -o "${TMP_ARCHIVE}" "${IMAGE_NAME}"
  kind load image-archive "${TMP_ARCHIVE}" --name "${CLUSTER_NAME}"
else
  echo "docker or podman is required to build image"
  exit 1
fi
