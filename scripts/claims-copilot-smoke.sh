#!/usr/bin/env bash
set -euo pipefail

FRONTEND_URL="${CLAIMS_COPILOT_URL:-http://127.0.0.1:4173}"
request='{"claim_id":"CL-DEMO-003","policy_id":"HOME-002","loss_date":"2025-03-01","narrative":"A sudden overnight flood entered the ground floor. The affected rooms, water depth, source, and repair estimate have not yet been confirmed."}'

if ! response="$(curl -fSs \
  -H 'Content-Type: application/json' \
  -d "${request}" \
  "${FRONTEND_URL%/}/api/v1/investigations")"; then
  echo "Claims investigation request failed; check frontend/API health."
  exit 1
fi

if ! jq -e '
  . as $brief
  | (.status == "answered" or .status == "insufficient_evidence")
    and (.trace_id | type == "string" and test("^[0-9a-f]{32}$"))
    and (.policy_id == "HOME-002")
    and (.latency_ms | type == "number" and . >= 0)
    and (if .status == "answered" then
      (.summary | length > 0)
      and (.findings | length > 0)
      and (.summary_citations | length > 0)
    else
      (.summary == "")
      and (.findings | length == 0)
      and (.summary_citations | length == 0)
      and (.evidence | length == 0)
    end)
    and ([.summary_citations[]?, .findings[]?.citations[]?] as $citations
      | all($citations[]; . as $citation
        | any($brief.evidence[];
          .chunk_id == $citation.chunk_id and .ref == $citation.ref)))
' <<<"${response}" >/dev/null; then
  echo "Claims investigation response failed contract validation."
  exit 1
fi

jq -r '
  "status=\(.status) trace_id=\(.trace_id) findings=\(.findings | length) " +
  "citations=((.summary_citations | length) + ([.findings[].citations[]] | length)) " +
  "evidence=\(.evidence | length) latency_ms=\(.latency_ms)"
' <<<"${response}"