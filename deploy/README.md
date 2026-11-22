# Deploying the BrAInBox backend

Two Cloud Run services, one Cloud Tasks queue and a hosted PostgreSQL with pgvector.

| Part | Where | Notes |
|---|---|---|
| `brainbox-api` | Cloud Run, public | The REST API the app and the admin portal call |
| `brainbox-ai` | Cloud Run, private | Only the API's service account may call it, and every call needs `X-Service-Token` |
| `brainbox-jobs` | Cloud Tasks | Slow AI jobs; the queue calls `POST /api/v1/internal/jobs/{id}/run` on the API |
| Database | Neon / Supabase (free tier) | PostgreSQL 15+ with the `vector` extension |
| Files and logins | Firebase Storage + Firebase Authentication | Same Google Cloud project |

Both services scale to zero when idle and to at most 2 instances, which keeps the cost inside
the student budget.

## One-time setup

You need the [gcloud CLI](https://cloud.google.com/sdk/docs/install), logged in as an owner of
the project (`gcloud auth login`).

```bash
export PROJECT_ID=your-firebase-project-id
./deploy/deploy.sh setup
```

This turns on the APIs and creates the Artifact Registry repository, the `brainbox-run`
service account and the queue.

### Secrets

Create each of these once in Secret Manager. The value is read from your keyboard, so it never
lands in your shell history.

```bash
printf '%s' 'THE VALUE' | gcloud secrets create NAME --project "$PROJECT_ID" --data-file=-
```

| Secret | Value |
|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://user:password@host/dbname?ssl=require` |
| `AI_SERVICE_TOKEN` | A long random string: `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `AUTH_CODE_SECRET` | Another long random string (hashes the 6-digit email codes) |
| `GEMINI_API_KEY` | From Google AI Studio |
| `CLOUDFLARE_API_TOKEN` | Workers AI token for illustrations (any text if you do not use it) |
| `SMTP_PASSWORD` | The app password of the mailbox that sends verification codes |
| `YOUTUBE_API_KEY` | YouTube Data API v3 key (any text if you do not use video recommendations) |

For a staging copy, create the first three again with the suffix `-staging`
(`DATABASE_URL-staging`, ...) and deploy with `ENV_NAME=staging`.

To change a secret later: `gcloud secrets versions add NAME --data-file=-`, then deploy again.

### Database

Create the database, enable pgvector (`CREATE EXTENSION IF NOT EXISTS vector;`), then:

```bash
export DATABASE_URL='postgresql+asyncpg://...'   # plus the other production settings
pip install -e ".[api,ai]"
./deploy/deploy.sh migrate     # optional: the API container also migrates when it starts
python scripts/seed_customer.py --admin-email you@example.com   # safe to run again
```

`scripts/seed_customer.py` loads the syllabus, base data, Learn topics, past papers, question
bank and knowledge base, then makes the admin (that person must have signed in once). See
`docs/deployment.md` (hosting, Neon, backups, logs, rollback).

### Firebase

1. Authentication: enable Email/Password and Google.
2. Storage: create the default bucket, then deploy the rules in this folder:
   `firebase deploy --only storage --project "$PROJECT_ID"` (add
   `"storage": {"rules": "deploy/storage.rules"}` to your `firebase.json`).
3. Android: add the app's SHA-1 and SHA-256 fingerprints (needed for Google sign-in).

## Deploy

```bash
export PROJECT_ID=your-firebase-project-id
export DATABASE_URL='postgresql+asyncpg://...'     # only for the migrate step
export SMTP_USER=you@gmail.com EMAIL_FROM='BrAInBox <you@gmail.com>'
export CORS_ORIGINS='https://your-project.web.app'  # where the admin portal is hosted
export AL_EXAM_DATES='{"2027": "2027-08-02"}'       # optional: the exam countdown

./deploy/deploy.sh migrate
./deploy/deploy.sh deploy
```

The script prints the API URL. Check it:

```bash
curl https://brainbox-api-xxxx.a.run.app/api/v1/health     # {"status":"ok","db":"ok"}
```

The API refuses to start in production with unsafe settings (default secrets, console email,
no storage bucket, debug switches on). If a deploy fails, the reason is in the revision's logs:
`gcloud run services logs read brainbox-api --region asia-south1 --limit 50`.

## Automatic deploys (GitHub Actions)

`.github/workflows/backend-deploy.yml` deploys `develop` to staging and `main` to production
after `backend-ci` passes. Give it a deployer key once:

```bash
gcloud iam service-accounts create brainbox-deployer --project "$PROJECT_ID"
for role in roles/run.admin roles/cloudbuild.builds.editor roles/artifactregistry.writer \
  roles/iam.serviceAccountUser roles/storage.admin roles/serviceusage.serviceUsageConsumer; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --role "$role" \
    --member "serviceAccount:brainbox-deployer@$PROJECT_ID.iam.gserviceaccount.com"
done
gcloud iam service-accounts keys create key.json \
  --iam-account "brainbox-deployer@$PROJECT_ID.iam.gserviceaccount.com"
```

Paste `key.json` into the repository secret `GCP_SA_KEY`, then delete the file. Add the
secrets `PROD_DATABASE_URL` and `STAGING_DATABASE_URL`, and the variable `GCP_PROJECT_ID`.
Until `GCP_PROJECT_ID` is set the workflow skips itself, so nothing breaks before you are ready.

## The apps

Point both Flutter apps at the API when you build them:

```bash
# Student app (signed release APK)
flutter build apk --release --dart-define=API_BASE_URL=https://brainbox-api-xxxx.a.run.app/api/v1

# Admin portal, hosted on Firebase Hosting
flutter build web --release --dart-define=API_BASE_URL=https://brainbox-api-xxxx.a.run.app/api/v1
firebase deploy --only hosting
```

See the frontend repository's `docs/deployment.md` for signing the APK.

## Running costs to watch

- Gemini, Cloud Vision and the image model have daily caps in the AI service
  (`GEMINI_DAILY_LIMIT`, `OCR_DAILY_LIMIT`, `IMAGE_DAILY_LIMIT`) and per-student caps in the API
  (`EVALUATIONS_DAILY_LIMIT`, `OCR_DAILY_LIMIT_PER_USER`, `VISUALS_DAILY_LIMIT`).
- Every model call is written to `ai_usage_log`; the admin portal's Analytics page adds it up.
- Set a budget alert in Google Cloud Billing for the project.
