# Deploying and running the BrAInBox backend

For the person who installs and operates the backend. It covers what to set up once, how to
deploy, how to make an admin, and what to do when something goes wrong.
`deploy/README.md` has the step-by-step Google Cloud commands; this page explains the whole.

## 1. What runs where

| Part | Recommended host | Notes |
|---|---|---|
| **API** (`api/Dockerfile`) | Google Cloud Run, public | The REST API used by the mobile app and the admin portal. Runs `alembic upgrade head` on start, then serves on `$PORT`. |
| **AI service** (`ai_service/Dockerfile`) | Google Cloud Run, private | The only part that calls Gemini, Cloud Vision and the image model. Only the API may call it (Cloud Run IAM + `X-Service-Token`). |
| **Job queue** | Google Cloud Tasks | Runs slow AI jobs (papers, notes, visuals) by calling the API back. |
| **Database** | Neon (PostgreSQL 15+ with `pgvector`) | All app data and the knowledge-base vectors. |
| **Logins, files** | Firebase Authentication + Firebase Storage | Same Google Cloud project as Cloud Run. |
| **Admin portal** | Firebase Hosting | Its origin goes in `CORS_ORIGINS`. |

Region: `asia-south1` (Mumbai) for Google Cloud and **AWS ap-southeast-1 (Singapore)** for Neon
are the closest to Sri Lanka.

Any host that runs Docker images also works (a VM with Docker Compose, Render, Fly.io...). Then
use `JOB_RUNNER=local` (jobs run inside the API), set `RATE_LIMIT_PROXY_HOPS` to the number of
proxies in front of the API, and give both containers the Firebase service-account file
(section 5).

## 2. What you must provide

| Item | Where it goes |
|---|---|
| Google Cloud / Firebase project (billing on, budget alert set) | `PROJECT_ID`, `FIREBASE_PROJECT_ID` |
| Neon project and database | `DATABASE_URL` (secret) |
| Gemini API key (Google AI Studio) | `GEMINI_API_KEY` (secret) |
| A mailbox that sends the 6-digit codes (SMTP host, user, app password) | `SMTP_HOST`, `SMTP_USER`, `EMAIL_FROM`, `SMTP_PASSWORD` (secret) |
| Two random secrets of 32+ characters | `AI_SERVICE_TOKEN`, `AUTH_CODE_SECRET` (secrets) |
| The admin portal's https address (e.g. `https://admin.your-school.lk`) | `CORS_ORIGINS` |
| Optional: Cloudflare Workers AI account + token (illustrations) | `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` |
| Optional: YouTube Data API key (video suggestions) | `YOUTUBE_API_KEY` |
| Optional: A/L exam dates | `AL_EXAM_DATES`, e.g. `{"2027": "2027-08-02"}` |
| The approved content: past papers, question bank, knowledge-base documents | `data/` (section 7) |

Make a random secret with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.

## 3. Settings (environment variables)

`.env.example` lists **every** variable with a one-line comment. In production set them on the
host, never in a file in the image (the image never contains `.env` or `secrets/`, see
`.dockerignore`). On Cloud Run, secrets live in Secret Manager (`deploy/README.md`).

Both services check their settings when they start with `ENVIRONMENT=prod` and **refuse to start**,
listing every problem at once, when something is unsafe or missing:

| Service | Must be set | Must NOT be |
|---|---|---|
| both | `DATABASE_URL`, `AI_SERVICE_TOKEN` (32+ chars), `FIREBASE_PROJECT_ID`, `STORAGE_BUCKET` | the dev defaults |
| API | `AUTH_CODE_SECRET` (32+ chars), `EMAIL_BACKEND=smtp` + `SMTP_HOST/USER/PASSWORD`, `CORS_ORIGINS` (exact `https://` origins), `JOBS_TARGET_URL` with `JOB_RUNNER=cloudtasks` | `DEV_LOGIN_ENABLED`, `DEBUG_SHOW_ANSWERS`, `DEV_EXPOSE_CODES` = true; `localhost` / `*` origins; `AI_SERVICE_URL` on localhost |
| AI service | `GEMINI_API_KEY`, `USE_FAKE_AI=false` | `LLM_PROVIDER=mock` |

`ENVIRONMENT` accepts only `dev`, `test`, `prod` (`production` is read as `prod`); a typo stops
the start-up instead of silently running with dev settings. The three dev switches cannot be
turned on at all while `ENVIRONMENT=prod`.

Everything else has a safe default (the daily limits, rate limits, model names, timeouts).

Rate limits (per API instance; Cloud Run runs at most 2): `RATE_LIMIT_AUTH_PER_MINUTE` (default
10 per IP on sign-up / email-code / password-reset) and `RATE_LIMIT_AI_PER_MINUTE` (default 20 per
login on the routes that start AI work). Too many requests get `429 RATE_LIMITED` with
`Retry-After`. The per-student daily caps (`EVALUATIONS_DAILY_LIMIT`, `PAPERS_DAILY_LIMIT`, ...)
and app-wide free-tier caps (`GEMINI_DAILY_LIMIT`, ...) apply on top.

## 4. Database (Neon)

1. Create a Neon project (region Singapore) and a database, e.g. `brainbox`.
2. In the SQL editor run `CREATE EXTENSION IF NOT EXISTS vector;`
3. Copy the **direct** connection string (turn *Connection pooling* off in the Connect dialog;
   the pooled `-pooler` host breaks the prepared statements the API uses) and rewrite it for
   the async driver:

   ```
   Neon gives: postgresql://USER:PASSWORD@ep-xxx.ap-southeast-1.aws.neon.tech/brainbox?sslmode=require&channel_binding=require
   Use:        postgresql+asyncpg://USER:PASSWORD@ep-xxx.ap-southeast-1.aws.neon.tech/brainbox?ssl=require
   ```

4. Store it as the `DATABASE_URL` secret. Keep the Neon password only in Secret Manager.

Neon's free plan suspends an idle database; the first request after a pause takes a second or two.

## 5. Firebase and the service account

1. Authentication: enable **Email/Password** and **Google**. Add the Android app's SHA-1 and
   SHA-256 fingerprints (Google sign-in needs them).
2. Storage: create the default bucket (`<project>.firebasestorage.app`, that is
   `STORAGE_BUCKET`) and deploy `deploy/storage.rules`.
3. Service account:
   - **On Cloud Run: no key file.** `deploy/deploy.sh setup` creates the `brainbox-run` service
     account with the roles it needs (Firebase Auth admin, Storage, Cloud Tasks, Vision, signing
     URLs, reading secrets); the services run as it. Leave `GOOGLE_APPLICATION_CREDENTIALS` empty.
   - **Elsewhere:** Firebase console → Project settings → Service accounts → *Generate new
     private key*. Mount that JSON into both containers as a read-only file (never bake it into
     the image, never commit it) and set `GOOGLE_APPLICATION_CREDENTIALS` to its path.
     Without it, logins still work but verifying emails, resetting passwords and deleting
     accounts fail.

## 6. Deploy

On Google Cloud (details and the one-time `setup` in `deploy/README.md`):

```bash
export PROJECT_ID=your-project-id
export SMTP_USER=codes@your-school.lk EMAIL_FROM='BrAInBox <codes@your-school.lk>'
export CORS_ORIGINS='https://admin.your-school.lk'
./deploy/deploy.sh deploy          # builds both images, deploys both services
curl https://<api-url>/api/v1/health   # {"status":"ok","db":"ok"}
```

### Migrations

The API container runs `alembic upgrade head` every time it starts (`deploy/start-api.sh`), so a
new version migrates the database before it serves. Two instances starting together are safe: a
PostgreSQL lock makes the second wait and then find nothing to do. If a migration fails, the new
container exits and the previous revision keeps serving. To migrate from your machine instead
(`./deploy/deploy.sh migrate`), set `RUN_MIGRATIONS=false` on the service.

### Health check

`GET /api/v1/health` → `200 {"status":"ok","db":"ok"}`, or `503` with `"db":"error"` when the
database cannot be reached. The API image has a Docker `HEALTHCHECK` on it; on Cloud Run point an
uptime check (Cloud Monitoring) at it.

## 7. First data (one command)

After the first deploy, from a machine with the production settings in its environment
(`DATABASE_URL`, `GEMINI_API_KEY`, `USE_FAKE_AI=false`, `STORAGE_BUCKET`, `FIREBASE_PROJECT_ID`,
`GOOGLE_APPLICATION_CREDENTIALS` with a key allowed to use Storage):

```bash
pip install -e ".[api,ai]"
python scripts/seed_customer.py --admin-email owner@your-school.lk
```

It loads, in order: the syllabus; community groups and app settings; the Learn tab topics and
the official sample note; every past paper file `data/questions/<year>_<part>.json`
(e.g. `2023_part_1.json`, imported as approved); the question bank
`data/questions/question_bank.json`; the approved knowledge-base documents in
`data/rag_sources/<syllabus|teacher_guides|approved_notes|marking_schemes>/`; and makes the
given email an admin.

* **Safe to run again.** Every step only adds what is missing; unchanged documents are not
  embedded again. Run it again after adding past papers or documents.
* The person in `--admin-email` must have signed in once (in the app or the Firebase console).
* `--skip knowledge-base` if there is no Gemini key yet; `--only past-papers` to load only one
  part. The file formats are in `data/questions/README.md` and `data/rag_sources/README.md`.
* Questions whose topic name matches no syllabus topic are skipped and listed in a `WARNING`
  at the end; fix the topic names and run again.
* The sample note's diagram link is valid for 7 days (the Storage maximum); run
  `python scripts/seed_customer.py --only learn` to renew it.

## 8. Admins

```bash
python scripts/make_admin.py someone@your-school.lk
```

Run with the production `DATABASE_URL` (and Firebase access, for people who never opened the
app). The person signs out and in again in the admin portal. Roles are kept in the database, not
in Firebase, and every `/api/v1/admin` route checks for the admin role. There is no "remove
admin" button yet; to take the role away run, in the Neon SQL editor,
`UPDATE users SET role = 'student' WHERE lower(email) = 'someone@your-school.lk';`

## 9. Logs

* With `ENVIRONMENT=prod` both services write **one JSON object per line** to stdout (`severity`,
  `message`, `time`, `logger`). Cloud Logging reads them directly: Cloud Run → service → *Logs*,
  or `gcloud run services logs read brainbox-api --region asia-south1 --limit 100`.
* No personal data: email addresses are replaced with `[email]` in every line (including
  tracebacks), database errors do not show the values of the query, and student answers are
  never logged. Request lines show method, path, status and client IP.
* `LOG_LEVEL` (default `INFO`) sets how much is written.
* Useful alerts: 5xx rate on the API, `/api/v1/health` uptime, and the Billing budget.

## 10. Backups

* **Neon** keeps a history of the database and can restore it to any moment inside the plan's
  history window (Neon console → *Restore*, or create a branch from a past time to inspect it
  first). Check the window of your plan; the free plan's is short.
* Also take a **daily `pg_dump`** kept outside Neon, e.g. from a scheduled job:

  ```bash
  pg_dump "postgresql://USER:PASSWORD@ep-xxx.aws.neon.tech/brainbox?sslmode=require" \
    --format=custom --file "brainbox-$(date +%F).dump"
  # restore into an empty database: pg_restore --no-owner --dbname "<url>" brainbox-YYYY-MM-DD.dump
  ```

* Firebase Storage (uploaded photos, visuals): enable Object Versioning or a scheduled copy on
  the bucket if uploads must survive deletion. Firebase Authentication users can be exported with
  `firebase auth:export`.
* Test a restore once before going live.

## 11. Rolling back

1. **Code:** Cloud Run keeps every revision.
   `gcloud run services update-traffic brainbox-api --region asia-south1 --to-revisions REVISION=100`
   (same for `brainbox-ai`). Revisions are listed with `gcloud run revisions list --service brainbox-api --region asia-south1`.
2. **Database:** migrations only add to the schema in normal releases, so an older revision
   usually runs fine on the newer schema; roll the code back first. If a migration itself must be
   undone, run `alembic downgrade -1` from a machine with the production `DATABASE_URL` **after**
   restoring a backup or checking the migration's `downgrade()` (it can drop columns and their
   data), and set `RUN_MIGRATIONS=false` until the fixed version is deployed (otherwise the next
   start migrates up again).
3. **Bad data:** restore Neon to a time before the problem (section 10), or restore the last dump
   into a new database and switch `DATABASE_URL`.

## 12. Secrets: rotating and leaks

* Change a secret: `gcloud secrets versions add NAME --data-file=-`, then deploy again.
* `AI_SERVICE_TOKEN` must be the same on both services; deploy both.
* Changing `AUTH_CODE_SECRET` only invalidates codes that are waiting to be used.
* A leaked Gemini / Cloudflare / SMTP key: revoke it at the provider first, then rotate.
* The repository never contains secrets (`.gitignore` blocks `.env`, `secrets/` and key files).
