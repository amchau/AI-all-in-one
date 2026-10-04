#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-http://127.0.0.1:8000}"

echo "Checking health..."
curl -sS "${API_URL}/healthz" | sed 's/{/\n{/g'

echo "Running investigate call..."
curl -sS -X POST "${API_URL}/v1/investigate" \
  -H 'content-type: application/json' \
  -d '{"claim_id":"CL-12345","prompt":"Investigate this sample insurance claim and summarize next steps."}' | sed 's/{/\n{/g'

for mode in dense hybrid hybrid_rerank; do
  echo "Running ${mode} RAG query..."
  response="$(curl -fSs -X POST "${API_URL}/v1/rag/query" \
    -H 'content-type: application/json' \
    -d "{\"question\":\"What water damage is covered under policy HOME-002?\",\"policy_id\":\"HOME-002\",\"loss_date\":\"2025-03-01\",\"guidance_as_of\":\"2026-01-01\",\"top_k\":5,\"mode\":\"${mode}\"}")"
    trace_metadata="$(printf '%s' "${response}" | python3 -c '
import json
import re
import sys

mode = sys.argv[1]
payload = json.load(sys.stdin)
if not isinstance(payload, dict):
    raise SystemExit("RAG response must be a JSON object")
if payload.get("mode") != mode:
    raise SystemExit(f"RAG response mode does not match request: {mode}")
if payload.get("status") not in {"answered", "insufficient_evidence"}:
    raise SystemExit("RAG response has an invalid answer status")
if not isinstance(payload.get("answer"), str):
    raise SystemExit("RAG response answer must be a string")
if not isinstance(payload.get("citations"), list):
    raise SystemExit("RAG response citations must be a list")
if not isinstance(payload.get("chunks"), list):
    raise SystemExit("RAG response chunks must be a list")
if not isinstance(payload.get("model"), str) or not payload["model"]:
    raise SystemExit("RAG response model must be a non-empty string")
latency_ms = payload.get("latency_ms")
if isinstance(latency_ms, bool) or not isinstance(latency_ms, int) or latency_ms < 0:
    raise SystemExit("RAG response latency_ms must be a non-negative integer")
trace_id = payload.get("trace_id")
if not isinstance(trace_id, str) or re.fullmatch(r"[0-9a-f]{32}", trace_id) is None:
    raise SystemExit("RAG response trace_id must be 32 lowercase hexadecimal characters")
print(payload["status"], trace_id)
' "${mode}")"
  read -r status trace_id <<<"${trace_metadata}"
  printf 'RAG trace mode=%s status=%s trace_id=%s\n' "${mode}" "${status}" "${trace_id}"
done
