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

# ── Secrets & provider config ────────────────────────────────────────────────
# Source local .env to read provider credentials.
if [[ -f "$REPO_ROOT/.env" ]]; then
  set -a; source "$REPO_ROOT/.env"; set +a
fi

# Reject obvious placeholder values (e.g. your_api_key_here) so we never sync a
# dummy credential. Syncing a placeholder is what let the service auto-detect a
# dead provider and return "Generation failed" dressed up as an honest fallback.
is_placeholder() {
  local v="$1"
  [[ -z "$v" ]] && return 0
  shopt -s nocasematch
  local hit=1
  [[ "$v" =~ ^(your[_-].*|.*_here|changeme|placeholder|todo|x{3,})$ ]] && hit=0
  shopt -u nocasematch
  return $hit
}

create_or_update_secret() {
  local name="$1" value="$2"
  if gcloud secrets describe "$name" --project "$PROJECT_ID" >/dev/null 2>&1; then
    printf '%s' "$value" | gcloud secrets versions add "$name" --data-file=- --project "$PROJECT_ID"
  else
    printf '%s' "$value" | gcloud secrets create "$name" \
      --data-file=- --replication-policy automatic --project "$PROJECT_ID"
  fi
}

grant_secret_access_once() {
  [[ -n "${_SA_GRANTED:-}" ]] && return 0
  PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format "value(projectNumber)")
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor" \
    --condition=None >/dev/null
  _SA_GRANTED=1
}

echo
echo "========================================"
echo "SYNCING PROVIDER SECRETS"
echo "========================================"
SECRET_FLAGS=""   # --set-secrets entries (secret-backed env vars)
ENV_FLAGS=""      # extra --set-env-vars entries (non-secret provider config)

# Active OpenAI-compatible provider: API key is a secret; provider/base_url/model
# are plain env vars. Explicit LLM_PROVIDER bypasses credential auto-detection.
if ! is_placeholder "${LLM_API_KEY:-}"; then
  create_or_update_secret "LLM_API_KEY" "$LLM_API_KEY"
  grant_secret_access_once
  SECRET_FLAGS="LLM_API_KEY=LLM_API_KEY:latest"
  [[ -n "${LLM_PROVIDER:-}" ]] && ENV_FLAGS="${ENV_FLAGS:+$ENV_FLAGS,}LLM_PROVIDER=${LLM_PROVIDER}"
  [[ -n "${LLM_BASE_URL:-}" ]] && ENV_FLAGS="${ENV_FLAGS:+$ENV_FLAGS,}LLM_BASE_URL=${LLM_BASE_URL}"
  [[ -n "${LLM_MODEL:-}" ]]    && ENV_FLAGS="${ENV_FLAGS:+$ENV_FLAGS,}LLM_MODEL=${LLM_MODEL}"
  echo "  Synced LLM_API_KEY (provider=${LLM_PROVIDER:-auto}, model=${LLM_MODEL:-default})."
else
  echo "  No real LLM_API_KEY in .env — skipping OpenAI-compatible provider."
fi

# Anthropic (optional).
if ! is_placeholder "${ANTHROPIC_API_KEY:-}"; then
  create_or_update_secret "ANTHROPIC_API_KEY" "$ANTHROPIC_API_KEY"
  grant_secret_access_once
  SECRET_FLAGS="${SECRET_FLAGS:+$SECRET_FLAGS,}ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest"
  echo "  Synced ANTHROPIC_API_KEY."
fi

# watsonx (optional): only when BOTH creds are real, not placeholders.
if ! is_placeholder "${WATSONX_API_KEY:-}" && ! is_placeholder "${WATSONX_PROJECT_ID:-}"; then
  create_or_update_secret "WATSONX_API_KEY"    "$WATSONX_API_KEY"
  create_or_update_secret "WATSONX_PROJECT_ID" "$WATSONX_PROJECT_ID"
  grant_secret_access_once
  SECRET_FLAGS="${SECRET_FLAGS:+$SECRET_FLAGS,}WATSONX_API_KEY=WATSONX_API_KEY:latest,WATSONX_PROJECT_ID=WATSONX_PROJECT_ID:latest"
  ENV_FLAGS="${ENV_FLAGS:+$ENV_FLAGS,}WATSONX_URL=${WATSONX_URL:-https://us-south.ml.cloud.ibm.com}"
  echo "  Synced watsonx secrets."
else
  echo "  No real watsonx credentials — skipping (placeholders are ignored)."
fi

if [[ -z "$SECRET_FLAGS" ]]; then
  echo "  WARNING: no provider credentials synced. The deployed service will have no LLM provider."
fi

# ── Deploy ───────────────────────────────────────────────────────────────────
echo
echo "========================================"
echo "DEPLOYING TO CLOUD RUN"
echo "========================================"
DEPLOY_ARGS=(
  --image                 "$IMAGE"
  --region                "$REGION"
  --project               "$PROJECT_ID"
  --port                  8080
  --memory                2Gi
  --cpu                   1
  --min-instances         0
  --max-instances         3
  --concurrency           4
  --allow-unauthenticated
  --set-env-vars          "VECTOR_STORE_BACKEND=chroma,CHROMA_PERSIST_DIR=/app/chroma_db,CDC_SVI_CSV=/app/data/svi_2022_us_tract.csv,POLICY_DOCS_DIR=/app/data/policy_docs,USE_GRANITE_GUARDIAN=${USE_GRANITE_GUARDIAN:-false}${ENV_FLAGS:+,$ENV_FLAGS}"
)
if [[ -n "$SECRET_FLAGS" ]]; then
  DEPLOY_ARGS+=(--set-secrets "$SECRET_FLAGS")
fi
gcloud run deploy "$SERVICE_NAME" "${DEPLOY_ARGS[@]}"

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
echo "Next step:"
echo "  Update orchestrate/skill_bridge_openapi.yaml — replace the servers.url with:"
echo "     $SERVICE_URL"
