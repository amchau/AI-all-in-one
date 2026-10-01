#!/usr/bin/env bash
set -euo pipefail

IMAGE_NAME="ai-api:stage1"
CLUSTER_NAME="ai-stage1"

if [[ -z "${KIND_EXPERIMENTAL_PROVIDER:-}" ]] && command -v podman >/dev/null 2>&1; then
  export KIND_EXPERIMENTAL_PROVIDER=podman
fi

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  docker build -t "${IMAGE_NAME}" apps/ai-api
  kind load docker-image "${IMAGE_NAME}" --name "${CLUSTER_NAME}"
elif command -v podman >/dev/null 2>&1; then
  podman build -t "${IMAGE_NAME}" apps/ai-api
  TMP_ARCHIVE="$(mktemp -t ai-api-image-XXXXXX.tar)"
  trap 'rm -f "${TMP_ARCHIVE}"' EXIT
  podman save -o "${TMP_ARCHIVE}" "${IMAGE_NAME}"
  kind load image-archive "${TMP_ARCHIVE}" --name "${CLUSTER_NAME}"
else
  echo "docker or podman is required to build image"
  exit 1
fi
