#!/usr/bin/env bash
set -euo pipefail

policy_dir="infrastructure/kubernetes/policies"
rendered_dir="$(mktemp -d)"
trap 'rm -rf "$rendered_dir"' EXIT
expected_kyverno_version="1.18.1"

command -v kyverno >/dev/null || {
  printf '%s\n' 'kyverno CLI is required for policy tests.' >&2
  exit 1
}

installed_kyverno_version="$(command kyverno version | awk '$1 == "Version:" { print $2 }')"
if [[ "$installed_kyverno_version" != "$expected_kyverno_version" ]]; then
  printf 'Kyverno CLI %s is required; found %s.\n' \
    "$expected_kyverno_version" "${installed_kyverno_version:-unknown}" >&2
  exit 1
fi

command kyverno test "$policy_dir/tests" --detailed-results --require-tests
command kubectl kustomize infrastructure/kubernetes/base > "$rendered_dir/resources.yaml"
if command kyverno apply \
  "$policy_dir/require-pod-resources.yaml" \
  "$policy_dir/require-pod-hardening.yaml" \
  --resource "$rendered_dir/resources.yaml" \
  --detailed-results \
  --audit-warn; then
  printf '%s\n' 'Offline audit complete. Findings are warnings; no cluster resources were changed.'
else
  audit_status=$?
  printf 'Offline audit returned %s; findings are report-only and no cluster resources were changed.\n' \
    "$audit_status" >&2
  exit "$audit_status"
fi