#!/usr/bin/env bash
set -euo pipefail

expected_context="kind-ai-stage1"
actual_context="$(command kubectl config current-context)"
if [[ "$actual_context" != "$expected_context" ]]; then
  printf 'Refusing Argo CD installation: expected context %s, got %s.\n' \
    "$expected_context" "$actual_context" >&2
  exit 1
fi

server_version="$(command kubectl --context "$expected_context" version -o json \
  | python3 -c 'import json, sys; print(json.load(sys.stdin)["serverVersion"]["gitVersion"])')"
if [[ "$server_version" == v1.37.* ]]; then
  printf 'Warning: installing Argo CD v3.5.5 on untested Kubernetes %s.\n' "$server_version" >&2
fi

command kubectl --context "$expected_context" apply --server-side \
  -k infrastructure/argocd/bootstrap
command kubectl --context "$expected_context" -n argocd wait \
  --for=condition=Available deployment --all --timeout=600s
command kubectl --context "$expected_context" -n argocd rollout status \
  statefulset/argocd-application-controller --timeout=600s