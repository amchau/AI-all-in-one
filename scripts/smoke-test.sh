#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-http://127.0.0.1:8000}"

echo "Checking health..."
curl -sS "${API_URL}/healthz" | sed 's/{/\n{/g'

echo "Running investigate call..."
curl -sS -X POST "${API_URL}/v1/investigate" \
  -H 'content-type: application/json' \
  -d '{"claim_id":"CL-12345","prompt":"Investigate this sample insurance claim and summarize next steps."}' | sed 's/{/\n{/g'
