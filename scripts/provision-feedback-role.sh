#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="ai-platform"
EXPECTED_CONTEXT="kind-ai-stage1"
ROLE_SQL="scripts/provision-feedback-role.sql"

if ! command -v kubectl >/dev/null 2>&1; then
  echo "kubectl is required to provision the feedback database role"
  exit 1
fi
if [[ ! -f "${ROLE_SQL}" ]]; then
  echo "Run this script from the repository root"
  exit 1
fi

KUBECTL=(kubectl --context "${EXPECTED_CONTEXT}")

"${KUBECTL[@]}" -n "${NAMESPACE}" exec -i deploy/postgres -- \
  sh -c 'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1' \
  < "${ROLE_SQL}"

echo "Feedback schema and dedicated LOGIN role provisioned; no password was set."
echo "Set the role password directly in an interactive local psql session:"
echo "kubectl --context ${EXPECTED_CONTEXT} -n ${NAMESPACE} exec -it deploy/postgres -- sh -c 'exec psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\"'"
echo "Then run: \\password claims_feedback"
echo "Set POSTGRES_FEEDBACK_PASSWORD in .env to the same value, then run ./scripts/deploy-stage1.sh."