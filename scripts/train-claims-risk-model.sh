#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_NAME="localhost/claims-risk-trainer:stage5.0"
OUTPUT_DIR="${ROOT_DIR}/docs/eval"
ARTIFACT_DIR="${ROOT_DIR}/artifacts/claims-risk"

if ! command -v podman >/dev/null 2>&1; then
  echo "podman is required to run the pinned Python 3.12 training image"
  exit 1
fi

if ! command -v flock >/dev/null 2>&1; then
  echo "flock is required to serialize model artifact writes"
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

mkdir -p "${OUTPUT_DIR}" "${ARTIFACT_DIR}"
podman build -t "${IMAGE_NAME}" -f "${ROOT_DIR}/apps/claims-risk-trainer/Dockerfile" "${ROOT_DIR}"
podman run --rm \
  --userns=keep-id \
  --user "$(id -u):$(id -g)" \
  -v "${OUTPUT_DIR}:/output/docs/eval:Z" \
  -v "${ARTIFACT_DIR}:/output/artifacts:Z" \
  "${IMAGE_NAME}" \
  --results /output/docs/eval/stage5-risk-model-results.json \
  --artifacts /output/artifacts
