#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-http://127.0.0.1:8000}"

echo "Checking health..."
curl -sS "${API_URL}/healthz" | sed 's/{/\n{/g'

echo "Running investigate call..."
curl -sS -X POST "${API_URL}/v1/investigate" \
  -H 'content-type: application/json' \
  -d '{"claim_id":"CL-12345","prompt":"Investigate this sample insurance claim and summarize next steps."}' | sed 's/{/\n{/g'

echo "Running dense RAG query..."
curl -fSs -X POST "${API_URL}/v1/rag/query" \
  -H 'content-type: application/json' \
  -d '{"question":"What water damage is covered under policy HOME-002?","policy_id":"HOME-002","loss_date":"2025-03-01","guidance_as_of":"2026-01-01","top_k":5}' | sed 's/{/\n{/g'
