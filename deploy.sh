#!/usr/bin/env bash
#
# Deploy the Saffron & Smoke backend to Cloud Run.
#
#   ./deploy.sh
#
# Prereqs (one-time): `gcloud auth login` and the project is set
#   gcloud config set project YOUR_PROJECT_ID
#
# This rebuilds the container from source (picks up code changes) AND applies
# env.cloudrun.yaml (DATABASE_URL, REDIS_URL, GOOGLE_API_KEY, etc.). Run it
# whenever backend code OR env values change. Frontend lives on Vercel — deploy
# that separately by pushing to its repo.

set -euo pipefail

SERVICE="saffron-smoke-api"
REGION="asia-south1"          # Mumbai. Change if you move regions.
ENV_FILE="env.cloudrun.yaml"  # gitignored — holds secrets

# Always run from this script's directory (the server/ folder).
cd "$(dirname "$0")"

if [ ! -f "$ENV_FILE" ]; then
  echo "✗ $ENV_FILE not found. Create it (see DEPLOY.md) before deploying." >&2
  exit 1
fi

echo "▶ Deploying $SERVICE to Cloud Run ($REGION)…"
gcloud run deploy "$SERVICE" \
  --source . \
  --region "$REGION" \
  --allow-unauthenticated \
  --memory 2Gi --cpu 1 --cpu-boost \
  --timeout 3600 \
  --min-instances 0 --max-instances 3 \
  --env-vars-file "$ENV_FILE"

# Show the URL and a couple of smoke checks.
URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')"
echo
echo "✓ Deployed: $URL"
echo "  health   : $(curl -s -m 15 "$URL/health" || echo 'no response')"
echo "  ws-ticket: $(curl -s -m 15 -X POST "$URL/auth/ws-ticket" -H 'content-type: application/json' -d '{}' || echo 'no response')"
echo
echo "Reminder — point Vercel at this URL:"
echo "  NEXT_PUBLIC_API_URL = $URL"
echo "  NEXT_PUBLIC_WS_URL  = ${URL/https:/wss:}/ws"
echo "  NEXT_PUBLIC_SHOW_WAKE_UP_GATE = 1"
