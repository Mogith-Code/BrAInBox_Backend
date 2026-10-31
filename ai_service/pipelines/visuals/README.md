# `pipelines/visuals`

| | |
|---|---|
| **Owner** | Mogith |
| **Purpose** | Plan and build study visuals: Mermaid diagrams (rendered by Kroki) or AI illustrations. |
| **Branch** | `feature/visuals-generation` |

| File | What it does | Job type | Uses RAG |
|---|---|---|---|
| `decide_visual.py` | Safety check + plan the visual (prompt `decide_visual.v2`), then build and store it. | `GENERATE_VISUAL` | yes |
| `diagram_mermaid.py` | `validate_mermaid`: strip ``` fences, allow only known diagram types, no `click` lines, max 5 000 chars. | - | - |
| `illustration.py` | Image prompt (style + "no text"), call the image provider, convert to PNG, read the size, store. | - | - |

Providers used: `get_llm()`, `get_diagram_renderer()` (Kroki), `get_image_generator()`, `get_storage()`.

## Job payload and result

```jsonc
// payload (made by api/modules/visuals/service.py)
{"visual_id": "...", "prompt": "Show how urine is formed", "visual_type": "process",
 "style": "flat_colour", "topic_title": "Excretion", "topic_id": "...",   // topic is optional
 "concept_name": "...", "concept_id": "..."}                              // optional
// result (the api saves it on the visuals row, then the job result becomes {"visual_id": ...})
{"visual_id": "...", "kind": "flowchart", "title": "...", "mermaid_code": "flowchart LR ...",
 "image_path": "visuals/<topic_id>/<visual_id>.png", "width": 552, "height": 136,
 "labels": [{"number": 1, "name": "...", "description": "...", "x": null, "y": null}],
 "alt_text": "...", "style": "flat_colour", "safety_passed": true,
 "prompt_version": "visuals/decide_visual.v2", "model": "gemini-2.5-flash"}
```

- `visual_type` is a hint: process → flowchart, comparison → table (a flowchart with one subgraph per item),
  structure → diagram, or an illustration if a picture really helps.
- Not about Biology study → `UserInputError` code `NOT_BIOLOGY`, "I can only draw Biology visuals." (the job fails).
- Invalid JSON or invalid Mermaid → the LLM is asked again (2 extra tries).
- RAG finds nothing (or fails) → the visual is still made, from standard A/L knowledge.
- Kroki down → the visual keeps `mermaid_code` only; the app renders it itself.
- Labels: numbered 1, 2, 3...; `x, y` (clamped to 0–1) only for illustrations, `null` for Mermaid kinds.

## Image providers (`IMAGE_PROVIDER`)

| Value | Model | Keys | Free? (checked 2026-11-01) |
|---|---|---|---|
| `gemini` | `IMAGE_MODEL=gemini-2.5-flash-image` via `generate_content(..., response_modalities=["IMAGE"])` | `GEMINI_API_KEY` | ⚠️ Google's [pricing page](https://ai.google.dev/gemini-api/docs/pricing) lists the Free Tier for this model as **"Not available"**; paid is about $0.039 per image. The [rate-limits page](https://ai.google.dev/gemini-api/docs/rate-limits) has no free RPM/RPD for it and says to check your own limits in [AI Studio](https://aistudio.google.com/rate-limit). Google also says this model shuts down on 15 March 2027. |
| `cloudflare` (default) | `@cf/black-forest-labs/flux-1-schnell` (Workers AI REST API) | `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` | ✅ [10 000 neurons per day free](https://developers.cloudflare.com/workers-ai/platform/pricing/) (shared by all models, resets 00:00 UTC). FLUX schnell costs 4.8 neurons per 512×512 tile + 9.6 per step; we use 4 steps, so roughly 40–45 neurons per image ≈ 200+ images a day. |

`imagen-*` models still work with `IMAGE_PROVIDER=gemini` (paid only).

**The default is `cloudflare` because it is free.** Diagrams (the most common kind) never use an image
model, only Gemini text + Kroki, so they are free with either provider.

When pictures are **not** possible, the visual is made as a free Mermaid diagram instead (the prompt
no longer offers "illustration"):
- no key for the chosen provider while real AI is on (we never show the fake 1×1 picture to students),
- today's `IMAGE_DAILY_LIMIT` is used up, or the last free picture went to another job a moment ago.

With `USE_FAKE_AI=true` (tests, offline dev) `FakeImageGenerator` returns a 1×1 PNG.

## Free-tier daily caps (whole app)

`ai_service/daily_limits.py` counts every real provider call in `ai_usage_log` (BEFORE the call, so retries
count too). At the cap the call is refused with `DailyLimitReached` (code `AI_DAILY_LIMIT`, message
"Today's free ... are used up. Please try again tomorrow."), which the app shows as the job `error`.
A `429` from Google after all retries gives the same kind of message. `0` = no cap (paid accounts only).

| Setting | Default | Counts | Resets | Free allowance (official pages, checked 2026-11-01) |
|---|---|---|---|---|
| `GEMINI_DAILY_LIMIT` | 200 | Gemini text requests (all features) | midnight Pacific | `gemini-2.5-flash` and `-flash-lite` text: "Free of charge" on the free tier; the per-project RPM/RPD are shown only in [AI Studio](https://aistudio.google.com/rate-limit). **Set this a little below your project's RPD.** |
| `EMBEDDING_DAILY_LIMIT` | 900 | embedding requests (1 per batch of up to 100 texts) | midnight Pacific | `gemini-embedding-001`: "Free of charge"; limits in AI Studio |
| `IMAGE_DAILY_LIMIT` | 200 | pictures | 00:00 UTC (Cloudflare) | 10 000 neurons/day ≈ 230 FLUX schnell pictures (shared with any other Workers AI use); 720 requests/minute |
| `OCR_DAILY_LIMIT` | 30 | Cloud Vision pages | midnight Pacific | Cloud Vision: first 1 000 units a month free |

Without billing turned on, Google and Cloudflare answer `429` instead of charging when their own limit is
reached, so the caps mainly give students a clear message (and protect you if billing is ever enabled).
Kroki (`kroki.io`) is free with no key; self-host it if you need more.


## Kroki (Mermaid → PNG)

`POST {KROKI_URL}/mermaid/png` with the Mermaid text as a `text/plain` body. Default `https://kroki.io`.
Self-host it ([docs](https://docs.kroki.io/kroki/setup/install/)): run the `yuzutech/kroki` container with its
`yuzutech/kroki-mermaid` companion and use a free port such as `8002` (8001 is the ai_service), e.g.
`KROKI_URL=http://localhost:8002`. In tests (`ENVIRONMENT=test`) a fake renderer is used, so tests never
touch the network.

## Rules

- Call AI only through `ai_service.providers` (`get_llm()`, `get_image_generator()`, ...). Never import an SDK here.
- Grounded pipelines use `ai_service.rag.retrieval.retriever.retrieve` + `ai_service.rag.context_builder.build_context`.
  Never query `document_chunks` directly.
- Prompts live in `ai_service/prompts/visuals/` and are versioned. v1 is kept; v2 is the one in use.
- Validate LLM output with a schema from `ai_service/schemas/llm_outputs.py` (`VisualDecision`, `VisualLabel`).
- Tests run with the fake providers (no API keys): `tests/ai_service/test_visuals_pipeline.py`.
