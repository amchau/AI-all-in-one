#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="ai-platform"
DEPLOYMENT="qdrant"
EXPECTED_CONTEXT="kind-ai-stage1"
VERSIONS=(v1.16.3 v1.17.1 v1.18.3 v1.19.1)

if [[ "${QDRANT_SNAPSHOT_CONFIRMED:-0}" != "1" ]]; then
  echo "Create and download an insurance_docs snapshot, then set QDRANT_SNAPSHOT_CONFIRMED=1"
  exit 1
fi
if ! command -v kubectl >/dev/null 2>&1; then
  echo "kubectl is required to upgrade Qdrant"
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

current_context="$(kubectl config current-context)"
if [[ "${current_context}" != "${EXPECTED_CONTEXT}" ]]; then
  echo "Refusing to upgrade Qdrant against kubectl context ${current_context}"
  exit 1
fi
KUBECTL=(kubectl --context "${EXPECTED_CONTEXT}")
current_image="$("${KUBECTL[@]}" -n "${NAMESPACE}" get pods -l app=qdrant \
  -o jsonpath='{.items[?(@.status.containerStatuses[0].ready==true)].spec.containers[0].image}')"
if [[ -z "${current_image}" ]]; then
  echo "No ready Qdrant pod found; refusing to resume the staged upgrade"
  exit 1
fi
current_version="${current_image##*:}"
case "${current_version}" in
  v1.15.4) start_index=0 ;;
  v1.16.3) start_index=1 ;;
  v1.17.1) start_index=2 ;;
  v1.18.3) start_index=3 ;;
  v1.19.1)
    echo "Qdrant is already at v1.19.1"
    exit 0
    ;;
  *)
    echo "Unsupported current Qdrant image version: ${current_version}"
    exit 1
    ;;
esac

for ((index = start_index; index < ${#VERSIONS[@]}; index++)); do
  version="${VERSIONS[index]}"
  echo "Upgrading Qdrant to ${version}..."
  "${KUBECTL[@]}" -n "${NAMESPACE}" set image "deployment/${DEPLOYMENT}" \
    "qdrant=qdrant/qdrant:${version}"
  "${KUBECTL[@]}" -n "${NAMESPACE}" rollout status "deployment/${DEPLOYMENT}" --timeout=10m
  running_image="$("${KUBECTL[@]}" -n "${NAMESPACE}" get pods -l app=qdrant \
    -o jsonpath='{.items[?(@.status.containerStatuses[0].ready==true)].spec.containers[0].image}')"
  if [[ "${running_image}" != "qdrant/qdrant:${version}" ]]; then
    echo "Ready Qdrant pod image did not reach ${version}; stopping upgrade"
    exit 1
  fi
done

echo "Qdrant upgrade complete at v1.19.1"