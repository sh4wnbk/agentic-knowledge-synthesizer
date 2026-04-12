#!/usr/bin/env bash
set -euo pipefail

APP_NAME="${APP_NAME:-data-bridge-api}"
PORT="8080"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "ERROR: Missing required command: $1"
    exit 1
  fi
}

require_cmd docker
require_cmd ibmcloud

if [[ -z "${ICR_REGION:-}" || -z "${ICR_NAMESPACE:-}" ]]; then
  echo "ERROR: Set ICR_REGION and ICR_NAMESPACE before running this script."
  exit 1
fi

if ! ibmcloud plugin show code-engine >/dev/null 2>&1; then
  echo "ERROR: IBM Cloud code-engine plugin is not installed."
  echo "Run: ibmcloud plugin install code-engine"
  exit 1
fi

if ! ibmcloud target >/dev/null 2>&1; then
  echo "ERROR: Not logged in to IBM Cloud."
  echo "Run: ibmcloud login"
  exit 1
fi

IMAGE="${ICR_REGION}.icr.io/${ICR_NAMESPACE}/agentic-knowledge-synthesizer-bridge:latest"

echo "========================================"
echo "BUILDING BRIDGE IMAGE"
echo "========================================"
docker build -f Dockerfile.bridge -t "${IMAGE}" .

echo
echo "========================================"
echo "LOGGING INTO IBM CONTAINER REGISTRY"
echo "========================================"
ibmcloud cr region-set "${ICR_REGION}"
ibmcloud cr login

echo
echo "========================================"
echo "PUSHING IMAGE"
echo "========================================"
docker push "${IMAGE}"

echo
echo "========================================"
echo "DEPLOYING TO CODE ENGINE"
echo "========================================"

if ibmcloud ce app get --name "${APP_NAME}" >/dev/null 2>&1; then
  echo "Updating existing app: ${APP_NAME}"
  ibmcloud ce app update \
    --name "${APP_NAME}" \
    --image "${IMAGE}" \
    --port "${PORT}" \
    --env PORT="${PORT}" \
    --env VECTOR_STORE_BACKEND=chroma \
    --env CHROMA_PERSIST_DIR=/tmp/chroma_db \
    --env CDC_SVI_CSV=/app/data/svi_2022_us_tract.csv \
    --env POLICY_DOCS_DIR=/app/data/policy_docs \
    --env WATSONX_URL=https://us-south.ml.cloud.ibm.com \
    --env WATSON_STT_URL=https://api.us-south.speech-to-text.watson.cloud.ibm.com
else
  echo "Creating new app: ${APP_NAME}"
  ibmcloud ce app create \
    --name "${APP_NAME}" \
    --image "${IMAGE}" \
    --port "${PORT}" \
    --env PORT="${PORT}" \
    --env VECTOR_STORE_BACKEND=chroma \
    --env CHROMA_PERSIST_DIR=/tmp/chroma_db \
    --env CDC_SVI_CSV=/app/data/svi_2022_us_tract.csv \
    --env POLICY_DOCS_DIR=/app/data/policy_docs \
    --env WATSONX_URL=https://us-south.ml.cloud.ibm.com \
    --env WATSON_STT_URL=https://api.us-south.speech-to-text.watson.cloud.ibm.com
fi

echo
echo "========================================"
echo "FETCHING PUBLIC URL"
echo "========================================"

PUBLIC_URL="$(ibmcloud ce app get --name "${APP_NAME}" --output json | python3 -c 'import json,sys; data=json.load(sys.stdin); print(data.get("status", {}).get("url", ""))')"

if [[ -z "${PUBLIC_URL}" ]]; then
  echo "ERROR: Could not determine Code Engine app URL."
  exit 1
fi

echo
echo "DEPLOYMENT COMPLETE"
echo "Public HTTPS URL: ${PUBLIC_URL}"
echo
echo "Next: put this URL into your Orchestrate tool connection base URL."
