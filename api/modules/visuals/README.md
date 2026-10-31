# `visuals` module

| | |
|---|---|
| **Owner** | Mogith |
| **Purpose** | Diagrams and illustrations for topics: AI generation, viewing, student reports. |
| **Tables** | `visuals`, `visual_reports` (+ `ai_jobs` for generation) |
| **Jira epic** | BRN-E05 Visual Learning *(placeholder key – replace with the real one)* |
| **Git branch** | `feature/visuals-generation` |
| **App** | BrainBox_front `apps/mobile/lib/features/visuals` (Figma B8–B10) |

## Endpoints

All need login (`Authorization: Bearer <Firebase ID token>`). JSON is snake_case.

| Method | Path | Body → response |
|---|---|---|
| GET | `/api/v1/topics/{topic_id}/visuals` | → `TopicVisualsOut {topic_id, topic_title, unit_code, unit_title, visuals: [VisualOut]}` |
| GET | `/api/v1/visuals/{visual_id}` | → `VisualOut` |
| POST | `/api/v1/visuals/generate` | `{prompt, visual_type, style, topic_id?}` → **202** `{job_id}` |
| GET | `/api/v1/jobs/{job_id}` | → `JobOut`; on success `result` = `{"visual_id": "..."}` (jobs module) |
| POST | `/api/v1/visuals/{visual_id}/report` | `{reason, details?}` → **201** `VisualReportOut` |
| GET | `/api/v1/admin/moderation/reports` | admin: reports queue with `visual_title` + `image_url` |

- `prompt`: 5–300 characters (spaces at the ends don't count).
- `visual_type`: `process` | `structure` | `comparison` (a hint for the AI).
- `style`: `flat_colour` | `textbook_line` | `cross_section`.
- `reason`: `wrong_label` | `inaccurate` | `unclear` | `offensive` | `other`; `details` ≤ 500 characters.

`VisualOut`: `id, title, topic_id, concept_id, kind ("diagram" | "flowchart" | "table" | "illustration"),
image_url, mermaid_code, alt_text, labels: [{number, name, description, x, y}], style, width, height,
is_ai_generated, is_verified, created_at`.

### Who sees what

| Visual | The student who made it | Other students |
|---|---|---|
| `approved` | yes | yes |
| `draft` / `pending_review` (own) | yes | no (404 `VISUAL_NOT_FOUND`) |
| `rejected` (e.g. not Biology) / `archived` (generation failed) | no | no |

Admins see every visual. Student visuals stay `draft`; an admin approves them in content review to share them.
The topic list leaves out the student's visuals that are still being made (no Mermaid code and no image yet).

### Error codes

| HTTP | Code | When |
|---|---|---|
| 401 | `UNAUTHORIZED` | no / bad token |
| 404 | `TOPIC_NOT_FOUND` | unknown `topic_id` |
| 404 | `VISUAL_NOT_FOUND` | unknown visual, or someone else's visual that is not approved |
| 404 | `JOB_NOT_FOUND` | unknown job, or another student's job |
| 409 | `ALREADY_REPORTED` | my earlier report of this visual is still pending |
| 422 | `VALIDATION_ERROR` | prompt too short/long, unknown `visual_type` / `style` / `reason` |
| 429 | `VISUAL_LIMIT_REACHED` | more than `VISUALS_DAILY_LIMIT` (20) requests in 24 hours; `retry_after` = seconds (also the `Retry-After` header) |
| job `error_code` | `NOT_BIOLOGY` | the job failed: "I can only draw Biology visuals." |
| job `error_code` | `AI_SERVICE_UNAVAILABLE` | the job failed: the AI is busy, try again later |
| job `error_code` | `AI_DAILY_LIMIT` | the job failed: today's free AI requests are used up (whole app), try tomorrow |

## How a visual is made (all free to run)

```
POST /visuals/generate
  └─ service.request_visual: topic check, daily limit, `visuals` row (draft, is_ai_generated)
     + GENERATE_VISUAL job {visual_id, prompt, visual_type, style, topic_title, topic_id}
        └─ (after the response) ai_service decide_visual.py
             1. RAG: syllabus facts for the topic
             2. Gemini (prompt decide_visual.v2): safety check, kind, title, labels, alt text,
                and Mermaid code OR an image description
             3a. Mermaid -> validate -> Kroki PNG -> storage   (Kroki down: Mermaid only)
             3b. illustration -> image model (no text in it) -> storage
        └─ service.run_visual_job saves the result on the row IN THE SAME COMMIT as
           job status "succeeded" (core/jobs `on_success`), so the app never sees
           "succeeded" before the visual exists. A failed job archives (or rejects) the row.
```

- **Diagrams, flowcharts, tables** (the default): the LLM writes Mermaid text, never pixels, so labels are
  always spelled right. Kroki renders the PNG; `mermaid_code` is always kept, so the app can render it itself.
- **Illustrations**: only when a picture really helps, and only while free pictures are left today
  (`IMAGE_DAILY_LIMIT`); otherwise the visual is made as a free Mermaid diagram. The image model draws with **no text**; the labels come
  as a list with `x, y` (0–1 of the image) where the app puts numbered markers.
- PNGs are stored at `visuals/{concept_id or topic_id or "general"}/{visual_id}.png`; `width` / `height` are read with Pillow.

## `image_url`: why signed URLs (and a dev route)

The phone loads images with a plain `Image.network(url)`, which can't send our login header. So:

- **With a bucket (`STORAGE_BUCKET` set, always in prod):** a Firebase Storage **signed URL**, made when the
  response is built and valid for `VISUAL_URL_EXPIRY_DAYS` (7, the maximum for signed URLs). The bucket stays
  private, nothing passes through our API, and a leaked link stops working after a week.
- **Dev without a bucket:** `http://<the address the app called>/api/v1/files/visuals/...`. The URL uses the
  host from the request, so it works from the Android emulator (`http://10.0.2.2:8000`) and from the computer
  (`http://localhost:8000`). Set `PUBLIC_BASE_URL` to override it. This route only serves files under
  `visuals/` (never student uploads) and is a 404 when a bucket is set or in prod.

Checked on the `Pixel_9` emulator: `GET http://10.0.2.2:8000/api/v1/files/visuals/...png` → 200 `image/png`.

## Settings

| Variable | Default | Where |
|---|---|---|
| `KROKI_URL` | `https://kroki.io` | ai_service |
| `IMAGE_PROVIDER` | `cloudflare` (free) or `gemini` (paid) | ai_service |
| `IMAGE_MODEL` | `gemini-2.5-flash-image` | ai_service |
| `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` | empty (= no pictures, diagrams only) | ai_service |
| `IMAGE_DAILY_LIMIT`, `GEMINI_DAILY_LIMIT` | 200, 200 | ai_service: free-tier caps for the whole app |
| `VISUALS_DAILY_LIMIT` | `20` | api |
| `VISUAL_URL_EXPIRY_DAYS` | `7` | api |
| `PUBLIC_BASE_URL` | empty (= request host) | api, dev only |

Free-tier notes for the image providers are in `ai_service/pipelines/visuals/README.md`.

## Try it

```bash
# 1. Start the database, the api and the ai_service (see the main README), then get a token:
python scripts/get_test_token.py
# 2. Ask for a visual (PowerShell: use curl.exe, and put the JSON in a file: -d "@body.json")
curl -X POST http://localhost:8000/api/v1/visuals/generate -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"prompt":"Show how urine is formed in the nephron","visual_type":"process","style":"flat_colour"}'
# 3. Poll the job, then load the visual
curl http://localhost:8000/api/v1/jobs/<job_id> -H "Authorization: Bearer $TOKEN"
curl http://localhost:8000/api/v1/visuals/<visual_id> -H "Authorization: Bearer $TOKEN"
```

From the app: `flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000/api/v1` (emulator).

## Files

| File | What goes in it |
|---|---|
| `router.py` | HTTP endpoints only (validate, check role, call service) + the dev file route |
| `schemas.py` | Pydantic request/response models (match the Flutter models) |
| `service.py` | Business logic: visibility, daily limit, job + saving the result, reports |
| `repository.py` | All SQL queries for this module |

Models live in `shared/db/models/visual.py` (migration `0004_visuals_generation`).
Tests: `tests/api/test_visuals.py` (API) and `tests/ai_service/test_visuals_pipeline.py` (pipeline).
