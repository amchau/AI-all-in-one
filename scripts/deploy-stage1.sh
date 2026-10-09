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

load_env_file() {
  local env_file="$1"
  [[ -f "${env_file}" ]] || return 0

  while IFS='=' read -r key value; do
    [[ -z "${key}" ]] && continue
    [[ "${key}" =~ ^[[:space:]]*# ]] && continue
    key="$(echo "${key}" | tr -d '[:space:]')"
    value="$(echo "${value:-}" | sed -e 's/^ *//' -e 's/ *$//')"
    value="${value%\"}"
    value="${value#\"}"
    case "${key}" in
      GROQ_API_KEY|OPENROUTER_API_KEY|LITELLM_MASTER_KEY|POSTGRES_DB|POSTGRES_USER|POSTGRES_PASSWORD|POSTGRES_INGEST_PASSWORD|POSTGRES_QUERY_PASSWORD|POSTGRES_WORKFLOW_PASSWORD|MINIO_ROOT_USER|MINIO_ROOT_PASSWORD|MINIO_ACCESS_KEY|MINIO_SECRET_KEY)
        printf -v "${key}" '%s' "${value}"
        ;;
    esac
  done < "${env_file}"
}

load_env_file .env

: "${GROQ_API_KEY:=set-me}"
: "${OPENROUTER_API_KEY:=set-me}"
: "${LITELLM_MASTER_KEY:=set-me}"
: "${POSTGRES_DB:=platform}"
: "${POSTGRES_USER:=app}"
: "${POSTGRES_PASSWORD:=set-me}"
: "${POSTGRES_INGEST_PASSWORD:=set-me}"
: "${POSTGRES_QUERY_PASSWORD:=set-me}"
: "${POSTGRES_WORKFLOW_PASSWORD:=set-me}"
: "${MINIO_ROOT_USER:=minio}"
: "${MINIO_ROOT_PASSWORD:=set-me}"
: "${MINIO_ACCESS_KEY:=${MINIO_ROOT_USER}}"
: "${MINIO_SECRET_KEY:=${MINIO_ROOT_PASSWORD}}"
export -n GROQ_API_KEY OPENROUTER_API_KEY LITELLM_MASTER_KEY POSTGRES_DB POSTGRES_USER \
  POSTGRES_PASSWORD POSTGRES_INGEST_PASSWORD POSTGRES_QUERY_PASSWORD POSTGRES_WORKFLOW_PASSWORD MINIO_ROOT_USER MINIO_ROOT_PASSWORD \
  MINIO_ACCESS_KEY MINIO_SECRET_KEY

assert_not_placeholder() {
  local key="$1"
  local value="$2"
  case "${value}" in
    ""|set-me|change-me*|dummy-key)
      echo "${key} is missing or placeholder. Set a real value in .env"
      exit 1
      ;;
  esac
}

assert_not_placeholder "GROQ_API_KEY" "${GROQ_API_KEY}"
assert_not_placeholder "OPENROUTER_API_KEY" "${OPENROUTER_API_KEY}"
assert_not_placeholder "LITELLM_MASTER_KEY" "${LITELLM_MASTER_KEY}"
assert_not_placeholder "POSTGRES_PASSWORD" "${POSTGRES_PASSWORD}"
assert_not_placeholder "POSTGRES_INGEST_PASSWORD" "${POSTGRES_INGEST_PASSWORD}"
assert_not_placeholder "POSTGRES_QUERY_PASSWORD" "${POSTGRES_QUERY_PASSWORD}"
assert_not_placeholder "POSTGRES_WORKFLOW_PASSWORD" "${POSTGRES_WORKFLOW_PASSWORD}"
assert_not_placeholder "MINIO_ROOT_PASSWORD" "${MINIO_ROOT_PASSWORD}"
assert_not_placeholder "MINIO_SECRET_KEY" "${MINIO_SECRET_KEY}"

EXPECTED_CONTEXT="kind-ai-stage1"
current_context="$(kubectl config current-context)"
if [[ "${current_context}" != "${EXPECTED_CONTEXT}" ]]; then
  echo "Refusing to deploy secrets and manifests against kubectl context ${current_context}"
  exit 1
fi
KUBECTL=(kubectl --context "${EXPECTED_CONTEXT}")

qdrant_lookup_file="$(mktemp)"
if "${KUBECTL[@]}" -n ai-platform get deployment qdrant >"${qdrant_lookup_file}" 2>&1; then
  rm -f "${qdrant_lookup_file}"
  qdrant_image="$("${KUBECTL[@]}" -n ai-platform get deployment qdrant \
    -o jsonpath='{.spec.template.spec.containers[?(@.name=="qdrant")].image}')"
  if [[ "${qdrant_image}" != "qdrant/qdrant:v1.19.1" ]]; then
    echo "Qdrant image is ${qdrant_image}; run the snapshot-backed staged upgrade before deploy"
    exit 1
  fi
  ready_qdrant_image="$("${KUBECTL[@]}" -n ai-platform get pods -l app=qdrant \
    -o jsonpath='{.items[?(@.status.containerStatuses[0].ready==true)].spec.containers[0].image}')"
  if [[ "${ready_qdrant_image}" != "qdrant/qdrant:v1.19.1" ]]; then
    echo "Qdrant v1.19.1 is not ready; wait for the snapshot-backed staged upgrade before deploy"
    exit 1
  fi
elif ! printf '%s\n' 'Error from server (NotFound): deployments.apps "qdrant" not found' \
  | cmp -s - "${qdrant_lookup_file}"; then
  cat "${qdrant_lookup_file}" >&2
  rm -f "${qdrant_lookup_file}"
  exit 1
else
  rm -f "${qdrant_lookup_file}"
fi

if job_status="$("${KUBECTL[@]}" -n ai-platform get job rag-ingest -o jsonpath='{.status.active}' 2>&1)"; then
  if [[ "${job_status}" =~ ^[1-9][0-9]*$ ]]; then
    echo "Refusing to deploy while rag-ingest is active"
    exit 1
  fi
elif [[ "${job_status}" != *"NotFound"* ]]; then
  printf '%s\n' "${job_status}" >&2
  exit 1
fi

STAGE1_SECRET_FILE="$(mktemp)"
INGEST_SECRET_FILE="$(mktemp)"
QUERY_SECRET_FILE="$(mktemp)"
WORKFLOW_SECRET_FILE="$(mktemp)"
trap 'rm -f "${STAGE1_SECRET_FILE}" "${INGEST_SECRET_FILE}" "${QUERY_SECRET_FILE}" "${WORKFLOW_SECRET_FILE}"' EXIT
chmod 600 "${STAGE1_SECRET_FILE}" "${INGEST_SECRET_FILE}" "${QUERY_SECRET_FILE}" "${WORKFLOW_SECRET_FILE}"
printf 'GROQ_API_KEY=%s\nOPENROUTER_API_KEY=%s\nLITELLM_MASTER_KEY=%s\nPOSTGRES_DB=%s\nPOSTGRES_USER=%s\nPOSTGRES_PASSWORD=%s\nMINIO_ROOT_USER=%s\nMINIO_ROOT_PASSWORD=%s\nMINIO_ACCESS_KEY=%s\nMINIO_SECRET_KEY=%s\n' \
  "${GROQ_API_KEY}" "${OPENROUTER_API_KEY}" "${LITELLM_MASTER_KEY}" \
  "${POSTGRES_DB}" "${POSTGRES_USER}" "${POSTGRES_PASSWORD}" \
  "${MINIO_ROOT_USER}" "${MINIO_ROOT_PASSWORD}" "${MINIO_ACCESS_KEY}" "${MINIO_SECRET_KEY}" \
  > "${STAGE1_SECRET_FILE}"
printf 'POSTGRES_PASSWORD=%s\n' "${POSTGRES_INGEST_PASSWORD}" > "${INGEST_SECRET_FILE}"
printf 'POSTGRES_PASSWORD=%s\n' "${POSTGRES_QUERY_PASSWORD}" > "${QUERY_SECRET_FILE}"
printf 'POSTGRES_PASSWORD=%s\n' "${POSTGRES_WORKFLOW_PASSWORD}" > "${WORKFLOW_SECRET_FILE}"
"${KUBECTL[@]}" get ns ai-platform >/dev/null 2>&1 || "${KUBECTL[@]}" create ns ai-platform

"${KUBECTL[@]}" -n ai-platform create secret generic stage1-secrets \
  --from-env-file="${STAGE1_SECRET_FILE}" \
  --dry-run=client -o yaml | "${KUBECTL[@]}" apply -f -

"${KUBECTL[@]}" -n ai-platform create secret generic rag-ingest-secrets \
  --from-env-file="${INGEST_SECRET_FILE}" \
  --dry-run=client -o yaml | "${KUBECTL[@]}" apply -f -

"${KUBECTL[@]}" -n ai-platform create secret generic rag-query-secrets \
  --from-env-file="${QUERY_SECRET_FILE}" \
  --dry-run=client -o yaml | "${KUBECTL[@]}" apply -f -

"${KUBECTL[@]}" -n ai-platform create secret generic claims-workflow-secrets \
  --from-env-file="${WORKFLOW_SECRET_FILE}" \
  --dry-run=client -o yaml | "${KUBECTL[@]}" apply -f -

"${KUBECTL[@]}" -n ai-platform delete job rag-ingest --ignore-not-found --wait=true
"${KUBECTL[@]}" apply -k infrastructure/kubernetes/base

"${KUBECTL[@]}" -n ai-platform rollout restart deploy/litellm
"${KUBECTL[@]}" -n ai-platform rollout restart deploy/ai-api
"${KUBECTL[@]}" -n ai-platform rollout restart deploy/claims-frontend

"${KUBECTL[@]}" -n ai-platform rollout status deploy/postgres --timeout=180s
"${KUBECTL[@]}" -n ai-platform rollout status deploy/qdrant --timeout=180s
"${KUBECTL[@]}" -n ai-platform rollout status deploy/minio --timeout=180s
"${KUBECTL[@]}" -n ai-platform rollout status deploy/litellm --timeout=180s
"${KUBECTL[@]}" -n ai-platform rollout status deploy/otel-collector --timeout=180s
if query_role_exists="$(
  printf "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rag_query');\n" |
    "${KUBECTL[@]}" -n ai-platform exec -i deploy/postgres -- \
      sh -c 'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -v ON_ERROR_STOP=1'
)"; then
  if [[ "${query_role_exists}" == "t" ]]; then
    if workflow_schema_ready="$(
      printf "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'claims_workflow') AND to_regclass('claims_workflow.workflows') IS NOT NULL;\n" |
        "${KUBECTL[@]}" -n ai-platform exec -i deploy/postgres -- \
          sh -c 'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -v ON_ERROR_STOP=1'
    )"; then
      if [[ "${workflow_schema_ready}" == "t" ]]; then
        "${KUBECTL[@]}" -n ai-platform rollout status deploy/ai-api --timeout=180s
      else
        echo "claims_workflow role/schema is not provisioned yet; run scripts/provision-workflow-role.sh, set its password, then deploy again."
      fi
    else
      echo "Could not verify claims_workflow provisioning. Refusing to claim API readiness."
      exit 1
    fi
  else
    echo "rag_query is not provisioned yet; API readiness waits until scripts/provision-rag-query-role.sh runs."
  fi
else
  echo "Could not verify whether rag_query is provisioned. Refusing to claim API readiness."
  exit 1
fi
"${KUBECTL[@]}" -n ai-platform rollout status deploy/reranker --timeout=900s
"${KUBECTL[@]}" -n ai-platform rollout status deploy/claims-frontend --timeout=180s

"${KUBECTL[@]}" -n ai-platform get pods
