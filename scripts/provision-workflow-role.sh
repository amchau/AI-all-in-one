#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="ai-platform"
EXPECTED_CONTEXT="kind-ai-stage1"
ROLE_SQL="scripts/provision-workflow-role.sql"

if ! command -v kubectl >/dev/null 2>&1; then
  echo "kubectl is required to provision the workflow database role"
  exit 1
fi
if [[ ! -f "${ROLE_SQL}" ]]; then
  echo "Run this script from the repository root"
  exit 1
fi

current_context="$(kubectl config current-context)"
if [[ "${current_context}" != "${EXPECTED_CONTEXT}" ]]; then
  echo "Refusing to provision the workflow role against kubectl context ${current_context}"
  exit 1
fi
KUBECTL=(kubectl --context "${EXPECTED_CONTEXT}")

"${KUBECTL[@]}" -n "${NAMESPACE}" exec -i deploy/postgres -- \
  sh -c 'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1' \
  < "${ROLE_SQL}"

echo "Set the role password interactively with:"
echo "kubectl --context ${EXPECTED_CONTEXT} -n ${NAMESPACE} exec -it deploy/postgres -- sh -c 'exec psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\"'"
echo "Then run: \\password claims_workflow"
echo "Set POSTGRES_WORKFLOW_PASSWORD to the same value in .env, then run scripts/deploy-stage1.sh."