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
| `gemini` (default) | `IMAGE_MODEL=gemini-2.5-flash-image` via `generate_content(..., response_modalities=["IMAGE"])` | `GEMINI_API_KEY` | ⚠️ Google's [pricing page](https://ai.google.dev/gemini-api/docs/pricing) lists the Free Tier for this model as **"Not available"**; paid is about $0.039 per image. The [rate-limits page](https://ai.google.dev/gemini-api/docs/rate-limits) has no free RPM/RPD for it and says to check your own limits in [AI Studio](https://aistudio.google.com/rate-limit). Google also says this model shuts down on 15 March 2027. |
| `cloudflare` | `@cf/black-forest-labs/flux-1-schnell` (Workers AI REST API) | `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` | ✅ [10 000 neurons per day free](https://developers.cloudflare.com/workers-ai/platform/pricing/) (shared by all models, resets 00:00 UTC). FLUX schnell costs 4.8 neurons per 512×512 tile + 9.6 per step; we use 4 steps, so roughly 40–45 neurons per image ≈ 200+ images a day. |

`imagen-*` models still work with `IMAGE_PROVIDER=gemini` (paid only).
Without a key for the chosen provider, or with `USE_FAKE_AI=true`, `FakeImageGenerator` returns a 1×1 PNG.

**To draw illustrations for free, use `IMAGE_PROVIDER=cloudflare`.** Diagrams (the default kind) never use
an image model, only Gemini text + Kroki, so they stay free either way.

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
