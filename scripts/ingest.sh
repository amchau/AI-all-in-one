#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="ai-platform"
JOB_NAME="rag-ingest"
MANIFEST="infrastructure/kubernetes/base/rag-ingest-job.yaml"
EXPECTED_CONTEXT="kind-ai-stage1"

if ! command -v kubectl >/dev/null 2>&1; then
  echo "kubectl is required to run ingestion"
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
  echo "Refusing to run ingestion against kubectl context ${current_context}"
  exit 1
fi
KUBECTL=(kubectl --context "${EXPECTED_CONTEXT}")

if active_pods="$("${KUBECTL[@]}" -n "${NAMESPACE}" get job "${JOB_NAME}" -o jsonpath='{.status.active}' 2>&1)"; then
  if [[ "${active_pods}" =~ ^[1-9][0-9]*$ ]]; then
    echo "Job ${JOB_NAME} is active; wait for it to finish before rerunning"
    exit 1
  fi
elif [[ "${active_pods}" != *"NotFound"* ]]; then
  printf '%s\n' "${active_pods}" >&2
  exit 1
fi

"${KUBECTL[@]}" -n "${NAMESPACE}" delete job "${JOB_NAME}" --ignore-not-found --wait=true
"${KUBECTL[@]}" apply -f "${MANIFEST}"
"${KUBECTL[@]}" -n "${NAMESPACE}" patch job "${JOB_NAME}" --type merge -p '{"spec":{"suspend":false}}'
deadline=$((SECONDS + 1800))
while (( SECONDS < deadline )); do
  conditions="$("${KUBECTL[@]}" -n "${NAMESPACE}" get job "${JOB_NAME}" -o jsonpath='{range .status.conditions[*]}{.type}={.status}{" "}{end}')"
  if [[ "${conditions}" == *"Complete=True"* ]]; then
    "${KUBECTL[@]}" -n "${NAMESPACE}" logs "job/${JOB_NAME}"
    exit 0
  fi
  if [[ "${conditions}" == *"Failed=True"* ]]; then
    "${KUBECTL[@]}" -n "${NAMESPACE}" logs "job/${JOB_NAME}" || true
    "${KUBECTL[@]}" -n "${NAMESPACE}" describe job "${JOB_NAME}"
    exit 1
  fi
  sleep 5
done

"${KUBECTL[@]}" -n "${NAMESPACE}" logs "job/${JOB_NAME}" || true
"${KUBECTL[@]}" -n "${NAMESPACE}" describe job "${JOB_NAME}"
echo "ingestion Job did not complete within 30 minutes"
exit 1