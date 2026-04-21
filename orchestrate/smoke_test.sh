#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:8080}"

echo "[SMOKE] Checking health endpoint"
curl -sS "${BASE_URL}/health"
echo

echo "[SMOKE] Checking intent-route skill"
curl -sS -X POST "${BASE_URL}/skills/intent-route" \
  -H 'Content-Type: application/json' \
  -d '{"raw_input":"Emergency Log: Tremors reported near a disposal well in Youngstown, OH. SVI tract identification required."}'
echo

echo "[SMOKE] Checking crisis-brief workflow"
curl -sS -X POST "${BASE_URL}/workflow/crisis-brief" \
  -H 'Content-Type: application/json' \
  -d '{"raw_input":"Emergency Log: Tremors reported near a disposal well in Youngstown, OH. SVI tract identification required."}'
echo

echo "[SMOKE] Checking incident-report workflow"
curl -sS -X POST "${BASE_URL}/workflow/incident-report" \
  -H 'Content-Type: application/json' \
  -d '{"raw_input":"M3.1 seismic event near Niles, Ohio. Requesting inter-agency routing brief.", "incident_id": "smoke-test-001"}'
echo

echo "[SMOKE] Done"