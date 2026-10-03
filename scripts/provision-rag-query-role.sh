#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="ai-platform"
EXPECTED_CONTEXT="kind-ai-stage1"
ROLE_SQL="scripts/provision-rag-query-role.sql"

if ! command -v kubectl >/dev/null 2>&1; then
  echo "kubectl is required to provision the query database role"
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
  echo "Refusing to provision the query role against kubectl context ${current_context}"
  exit 1
fi
KUBECTL=(kubectl --context "${EXPECTED_CONTEXT}")

run_psql() {
  "${KUBECTL[@]}" -n "${NAMESPACE}" exec -i deploy/postgres -- \
    sh -c 'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1'
}

run_psql < "${ROLE_SQL}"

echo "Set the role password interactively with:"
echo "kubectl --context ${EXPECTED_CONTEXT} -n ${NAMESPACE} exec -it deploy/postgres -- sh -c 'exec psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\"'"
echo "Then run: \\password rag_query"
echo "Set POSTGRES_QUERY_PASSWORD to the same value in .env, then run scripts/deploy-stage1.sh."