#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_NAME="localhost/claims-risk-service:stage5.0"
CLUSTER_NAME="ai-stage1"
ARTIFACT_DIR="${ROOT_DIR}/artifacts/claims-risk"
RESULTS_PATH="${ROOT_DIR}/docs/eval/stage5-risk-model-results.json"

if ! PYTHONPATH="${ROOT_DIR}" python3 -m ml.claims_risk.artifacts \
  --model "${ARTIFACT_DIR}/model.json" \
  --metadata "${ARTIFACT_DIR}/metadata.json" \
  --results "${RESULTS_PATH}"; then
  echo "Refusing to build without a valid artifact from the latest passing evaluation"
  exit 1
fi

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

if [[ -z "${KIND_EXPERIMENTAL_PROVIDER:-}" ]] && command -v podman >/dev/null 2>&1; then
  export KIND_EXPERIMENTAL_PROVIDER=podman
fi

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  docker build -t "${IMAGE_NAME}" -f "${ROOT_DIR}/apps/claims-risk-service/Dockerfile" "${ROOT_DIR}"
  kind load docker-image "${IMAGE_NAME}" --name "${CLUSTER_NAME}"
elif command -v podman >/dev/null 2>&1; then
  podman build -t "${IMAGE_NAME}" -f "${ROOT_DIR}/apps/claims-risk-service/Dockerfile" "${ROOT_DIR}"
  TMP_ARCHIVE="$(mktemp -t claims-risk-service-image-XXXXXX.tar)"
  trap 'rm -f "${TMP_ARCHIVE}"' EXIT
  podman save -o "${TMP_ARCHIVE}" "${IMAGE_NAME}"
  kind load image-archive "${TMP_ARCHIVE}" --name "${CLUSTER_NAME}"
else
  echo "docker or podman is required to build the image"
  exit 1
fi
