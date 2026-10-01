#!/usr/bin/env bash
set -euo pipefail

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
      GROQ_API_KEY|LITELLM_MASTER_KEY|POSTGRES_DB|POSTGRES_USER|POSTGRES_PASSWORD|MINIO_ROOT_USER|MINIO_ROOT_PASSWORD|MINIO_ACCESS_KEY|MINIO_SECRET_KEY)
        export "${key}=${value}"
        ;;
    esac
  done < "${env_file}"
}

load_env_file .env

: "${GROQ_API_KEY:=set-me}"
: "${LITELLM_MASTER_KEY:=set-me}"
: "${POSTGRES_DB:=platform}"
: "${POSTGRES_USER:=app}"
: "${POSTGRES_PASSWORD:=set-me}"
: "${MINIO_ROOT_USER:=minio}"
: "${MINIO_ROOT_PASSWORD:=set-me}"
: "${MINIO_ACCESS_KEY:=${MINIO_ROOT_USER}}"
: "${MINIO_SECRET_KEY:=${MINIO_ROOT_PASSWORD}}"

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
assert_not_placeholder "LITELLM_MASTER_KEY" "${LITELLM_MASTER_KEY}"
assert_not_placeholder "POSTGRES_PASSWORD" "${POSTGRES_PASSWORD}"
assert_not_placeholder "MINIO_ROOT_PASSWORD" "${MINIO_ROOT_PASSWORD}"
assert_not_placeholder "MINIO_SECRET_KEY" "${MINIO_SECRET_KEY}"

kubectl get ns ai-platform >/dev/null 2>&1 || kubectl create ns ai-platform

kubectl -n ai-platform create secret generic stage1-secrets \
  --from-literal=GROQ_API_KEY="${GROQ_API_KEY}" \
  --from-literal=LITELLM_MASTER_KEY="${LITELLM_MASTER_KEY}" \
  --from-literal=POSTGRES_DB="${POSTGRES_DB}" \
  --from-literal=POSTGRES_USER="${POSTGRES_USER}" \
  --from-literal=POSTGRES_PASSWORD="${POSTGRES_PASSWORD}" \
  --from-literal=MINIO_ROOT_USER="${MINIO_ROOT_USER}" \
  --from-literal=MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD}" \
  --from-literal=MINIO_ACCESS_KEY="${MINIO_ACCESS_KEY}" \
  --from-literal=MINIO_SECRET_KEY="${MINIO_SECRET_KEY}" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl apply -k infrastructure/kubernetes/base

kubectl -n ai-platform rollout restart deploy/litellm

kubectl -n ai-platform rollout status deploy/postgres --timeout=180s
kubectl -n ai-platform rollout status deploy/qdrant --timeout=180s
kubectl -n ai-platform rollout status deploy/minio --timeout=180s
kubectl -n ai-platform rollout status deploy/litellm --timeout=180s
kubectl -n ai-platform rollout status deploy/otel-collector --timeout=180s
kubectl -n ai-platform rollout status deploy/ai-api --timeout=180s

kubectl -n ai-platform get pods
