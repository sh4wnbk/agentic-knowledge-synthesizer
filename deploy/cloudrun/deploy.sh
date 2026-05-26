#!/usr/bin/env bash
set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────────────
PROJECT_ID="${GCP_PROJECT_ID:?Set GCP_PROJECT_ID environment variable}"
REGION="us-central1"
SERVICE_NAME="aegis-skill-server"
REPO_NAME="aegis"
IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO_NAME/$SERVICE_NAME:latest"

# ── Prerequisites ────────────────────────────────────────────────────────────
require_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "ERROR: Missing required command: $1"; exit 1; }
}
require_cmd docker
require_cmd gcloud

# ── Enable APIs ──────────────────────────────────────────────────────────────
echo "Enabling required GCP APIs..."
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  --project "$PROJECT_ID"

# ── Artifact Registry ────────────────────────────────────────────────────────
echo "Creating Artifact Registry repository (if not exists)..."
gcloud artifacts repositories describe "$REPO_NAME" \
  --location "$REGION" --project "$PROJECT_ID" >/dev/null 2>&1 || \
gcloud artifacts repositories create "$REPO_NAME" \
  --repository-format docker \
  --location "$REGION" \
  --project "$PROJECT_ID" \
  --description "AEGIS skill server images"

gcloud auth configure-docker "$REGION-docker.pkg.dev" --quiet

# ── Build & push ─────────────────────────────────────────────────────────────
echo "========================================"
echo "BUILDING IMAGE"
echo "========================================"
# Run from repo root so Dockerfile COPY . . picks up all application files
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
docker build --platform linux/amd64 -t "$IMAGE" "$REPO_ROOT"

echo
echo "========================================"
echo "PUSHING IMAGE"
echo "========================================"
docker push "$IMAGE"

# ── Secrets ──────────────────────────────────────────────────────────────────
# Source local .env to read WATSONX_API_KEY and WATSONX_PROJECT_ID
if [[ -f "$REPO_ROOT/.env" ]]; then
  set -a; source "$REPO_ROOT/.env"; set +a
fi

create_or_update_secret() {
  local name="$1" value="$2"
  if gcloud secrets describe "$name" --project "$PROJECT_ID" >/dev/null 2>&1; then
    printf '%s' "$value" | gcloud secrets versions add "$name" --data-file=- --project "$PROJECT_ID"
  else
    printf '%s' "$value" | gcloud secrets create "$name" \
      --data-file=- --replication-policy automatic --project "$PROJECT_ID"
  fi
}

echo
echo "========================================"
echo "SYNCING SECRETS"
echo "========================================"
create_or_update_secret "WATSONX_API_KEY"    "${WATSONX_API_KEY:?Set WATSONX_API_KEY in .env}"
create_or_update_secret "WATSONX_PROJECT_ID" "${WATSONX_PROJECT_ID:?Set WATSONX_PROJECT_ID in .env}"

# Grant Cloud Run's default compute SA permission to read secrets
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format "value(projectNumber)")
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor" \
  --condition=None >/dev/null

# ── Deploy ───────────────────────────────────────────────────────────────────
echo
echo "========================================"
echo "DEPLOYING TO CLOUD RUN"
echo "========================================"
gcloud run deploy "$SERVICE_NAME" \
  --image                 "$IMAGE" \
  --region                "$REGION" \
  --project               "$PROJECT_ID" \
  --port                  8080 \
  --memory                2Gi \
  --cpu                   1 \
  --min-instances         0 \
  --max-instances         3 \
  --concurrency           4 \
  --allow-unauthenticated \
  --set-env-vars          "VECTOR_STORE_BACKEND=chroma,CHROMA_PERSIST_DIR=/app/chroma_db,CDC_SVI_CSV=/app/data/svi_2022_us_tract.csv,POLICY_DOCS_DIR=/app/data/policy_docs,WATSONX_URL=${WATSONX_URL:-https://us-south.ml.cloud.ibm.com},USE_GRANITE_GUARDIAN=${USE_GRANITE_GUARDIAN:-false}" \
  --set-secrets           "WATSONX_API_KEY=WATSONX_API_KEY:latest,WATSONX_PROJECT_ID=WATSONX_PROJECT_ID:latest"

# ── Output ───────────────────────────────────────────────────────────────────
SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
  --region "$REGION" --project "$PROJECT_ID" \
  --format "value(status.url)")

echo
echo "========================================"
echo "DEPLOYMENT COMPLETE"
echo "Service URL: $SERVICE_URL"
echo "========================================"
echo
echo "Next steps:"
echo "  1. Update orchestrate/skill_bridge_openapi.yaml — replace the servers.url with:"
echo "     $SERVICE_URL"
echo "  2. Delete railway.toml"
