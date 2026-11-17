#!/usr/bin/env bash
# Deploy the BrAInBox backend to Google Cloud Run (two services + one Cloud Tasks queue).
#
#   ./deploy/deploy.sh setup     one time: APIs, service accounts, queue, Artifact Registry
#   ./deploy/deploy.sh migrate   apply database migrations (run before every deploy)
#   ./deploy/deploy.sh deploy    build both images and deploy both services
#
# Settings come from the environment (see deploy/README.md):
#   PROJECT_ID   Google Cloud project (the same one as Firebase)       required
#   REGION       default asia-south1 (Mumbai, the closest to Sri Lanka)
#   ENV_NAME     "prod" (default) or "staging": used in the service names
#
# Secrets are NOT in this file. They live in Secret Manager under the names listed in
# deploy/README.md and are mounted into the services as environment variables.
set -euo pipefail

: "${PROJECT_ID:?Set PROJECT_ID to your Google Cloud project id}"
REGION="${REGION:-asia-south1}"
ENV_NAME="${ENV_NAME:-prod}"
SUFFIX=""
[ "$ENV_NAME" = "prod" ] || SUFFIX="-$ENV_NAME"

API_SERVICE="brainbox-api$SUFFIX"
AI_SERVICE="brainbox-ai$SUFFIX"
QUEUE="brainbox-jobs$SUFFIX"
REPO="brainbox"
RUN_SA="brainbox-run@$PROJECT_ID.iam.gserviceaccount.com"
IMAGE_BASE="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO"
TAG="${TAG:-$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)}"
# Both services read these secrets (name in Secret Manager = name of the variable).
SHARED_SECRETS="DATABASE_URL=DATABASE_URL$SUFFIX:latest,AI_SERVICE_TOKEN=AI_SERVICE_TOKEN$SUFFIX:latest"
API_SECRETS="$SHARED_SECRETS,AUTH_CODE_SECRET=AUTH_CODE_SECRET$SUFFIX:latest,SMTP_PASSWORD=SMTP_PASSWORD:latest,YOUTUBE_API_KEY=YOUTUBE_API_KEY:latest"
AI_SECRETS="$SHARED_SECRETS,GEMINI_API_KEY=GEMINI_API_KEY:latest,CLOUDFLARE_API_TOKEN=CLOUDFLARE_API_TOKEN:latest"

g() { gcloud --project "$PROJECT_ID" "$@"; }

setup() {
  g services enable run.googleapis.com cloudtasks.googleapis.com artifactregistry.googleapis.com \
    secretmanager.googleapis.com cloudbuild.googleapis.com vision.googleapis.com \
    youtube.googleapis.com
  g artifacts repositories describe "$REPO" --location "$REGION" >/dev/null 2>&1 ||
    g artifacts repositories create "$REPO" --repository-format docker --location "$REGION"
  g iam service-accounts describe "$RUN_SA" >/dev/null 2>&1 ||
    g iam service-accounts create brainbox-run --display-name "BrAInBox Cloud Run"
  # What the services may do: read their secrets, create tasks, use Storage / Firebase Auth /
  # Vision, and sign download URLs.
  for role in roles/secretmanager.secretAccessor roles/cloudtasks.enqueuer \
    roles/storage.objectAdmin roles/firebaseauth.admin roles/iam.serviceAccountTokenCreator \
    roles/serviceusage.serviceUsageConsumer; do
    g projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:$RUN_SA" \
      --role "$role" --condition None >/dev/null
  done
  g tasks queues describe "$QUEUE" --location "$REGION" >/dev/null 2>&1 ||
    g tasks queues create "$QUEUE" --location "$REGION" \
      --max-attempts 3 --min-backoff 10s --max-concurrent-dispatches 4
  echo "Setup done. Now create the secrets listed in deploy/README.md."
}

migrate() {
  # Runs on your machine (or in CI) against the production database.
  : "${DATABASE_URL:?Set DATABASE_URL to the production database to migrate it}"
  alembic upgrade head
}

build() {
  g builds submit --tag "$IMAGE_BASE/api:$TAG" --timeout 20m \
    --config /dev/stdin . <<EOF
steps:
  - name: gcr.io/cloud-builders/docker
    args: [build, -f, api/Dockerfile, -t, $IMAGE_BASE/api:$TAG, .]
  - name: gcr.io/cloud-builders/docker
    args: [build, -f, ai_service/Dockerfile, -t, $IMAGE_BASE/ai:$TAG, .]
images: [$IMAGE_BASE/api:$TAG, $IMAGE_BASE/ai:$TAG]
EOF
}

deploy() {
  build
  # 1. The AI service: internal. --no-allow-unauthenticated means only callers with an IAM
  #    invoker role get in, and every request also needs the X-Service-Token secret.
  g run deploy "$AI_SERVICE" --image "$IMAGE_BASE/ai:$TAG" --region "$REGION" \
    --service-account "$RUN_SA" --no-allow-unauthenticated \
    --min-instances 0 --max-instances 2 --cpu 1 --memory 1Gi --timeout 600 --concurrency 8 \
    --set-secrets "$AI_SECRETS" \
    --set-env-vars "ENVIRONMENT=prod,USE_FAKE_AI=false,FIREBASE_PROJECT_ID=$PROJECT_ID,STORAGE_BUCKET=${STORAGE_BUCKET:-$PROJECT_ID.firebasestorage.app},IMAGE_PROVIDER=${IMAGE_PROVIDER:-cloudflare},CLOUDFLARE_ACCOUNT_ID=${CLOUDFLARE_ACCOUNT_ID:-}"
  AI_URL="$(g run services describe "$AI_SERVICE" --region "$REGION" --format 'value(status.url)')"
  g run services add-iam-policy-binding "$AI_SERVICE" --region "$REGION" \
    --member "serviceAccount:$RUN_SA" --role roles/run.invoker >/dev/null

  # 2. The public API. --no-cpu-throttling keeps the CPU on after a response is sent, which
  #    the in-process background jobs (notes, visuals, uploads) need; the instance still
  #    scales to zero when idle.
  g run deploy "$API_SERVICE" --image "$IMAGE_BASE/api:$TAG" --region "$REGION" \
    --service-account "$RUN_SA" --allow-unauthenticated --no-cpu-throttling \
    --min-instances 0 --max-instances 2 --cpu 1 --memory 512Mi --timeout 600 --concurrency 40 \
    --set-secrets "$API_SECRETS" \
    --set-env-vars "^##^ENVIRONMENT=prod##FIREBASE_PROJECT_ID=$PROJECT_ID##STORAGE_BUCKET=${STORAGE_BUCKET:-$PROJECT_ID.firebasestorage.app}##AI_SERVICE_URL=$AI_URL##AI_SERVICE_AUDIENCE=$AI_URL##JOB_RUNNER=cloudtasks##CLOUD_TASKS_LOCATION=$REGION##CLOUD_TASKS_QUEUE=$QUEUE##CLOUD_TASKS_SERVICE_ACCOUNT=$RUN_SA##EMAIL_BACKEND=smtp##SMTP_HOST=${SMTP_HOST:-smtp.gmail.com}##SMTP_PORT=${SMTP_PORT:-587}##SMTP_USER=${SMTP_USER:-}##EMAIL_FROM=${EMAIL_FROM:-BrAInBox <no-reply@example.com>}##CORS_ORIGINS=${CORS_ORIGINS:-https://$PROJECT_ID.web.app}##ADMIN_ORIGINS=${ADMIN_ORIGINS:-}##AL_EXAM_DATES=${AL_EXAM_DATES:-{\}}"
  API_URL="$(g run services describe "$API_SERVICE" --region "$REGION" --format 'value(status.url)')"
  # The queue calls the API back on its own public URL.
  g run services update "$API_SERVICE" --region "$REGION" \
    --update-env-vars "JOBS_TARGET_URL=$API_URL" >/dev/null

  echo
  echo "API:        $API_URL/api/v1   (docs: $API_URL/docs)"
  echo "AI service: $AI_URL (internal)"
  echo "Health:     curl $API_URL/api/v1/health"
}

case "${1:-}" in
  setup) setup ;;
  migrate) migrate ;;
  deploy) deploy ;;
  *) echo "Usage: $0 setup | migrate | deploy" && exit 1 ;;
esac
