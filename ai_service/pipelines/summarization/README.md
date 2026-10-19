# `pipelines/summarization`

| | |
|---|---|
| **Owner** | Samni |
| **Purpose** | Summarise a student's uploaded study material. |
| **Branch** | `feature/ai-summarization` |

| File | What it does | Job type | Uses RAG |
|---|---|---|---|
| `preprocess.py` | Prepare uploaded text before summarising (extract, clean, detect language). | - | - |
| `chunker.py` | Split long uploads into parts that fit the LLM context. | - | - |
| `summarize.py` | Topic-based summary of the student's notes, or of approved sources (SCRUM-37). | `SUMMARIZE_UPLOAD` | only without notes |

## Topic-based summaries (`summarize.py`)

```json
{"topic_title": "Osmosis", "text": "...notes...", "topic_id": "...", "unit_title": "Unit 2"}
```

Only `topic_title` is required.

- **With `text`**: the notes are cleaned (`preprocess`) and summarised. Notes longer than 1500 words
  are split (`chunker`), each part is summarised with `summarize_chunk.v1`, and the parts are merged.
- **Without `text`**: approved sources for the topic are retrieved with RAG and summarised with
  `[n]` citations. No sources -> `NoContextError` (we never invent a summary).

The final summary uses `summarize_topic.v1` and is validated as `TopicSummary`. Result:

```json
{"title": "...", "body_md": "...", "key_points": [], "key_terms": [],
 "topic_id": "..." , "source": "notes | rag", "citations": [],
 "prompt_version": "summarization/summarize_topic.v1"}
```

`body_md`, `topic_id` and `prompt_version` match the `summaries` table. Tests: `tests/ai_service/test_summarization.py`.

## Rules

- Call AI only through `ai_service.providers` (`get_llm()`, `get_embedder()`, ...). Never import an SDK here.
- Grounded pipelines use `ai_service.rag.retrieval.retriever.retrieve` + `ai_service.rag.context_builder.build_context`.
  Never query `document_chunks` directly.
- Prompts live in `ai_service/prompts/summarization/` and are versioned (`name.v1.j2`). Return the prompt id with the result.
- Validate LLM output with a schema from `ai_service/schemas/llm_outputs.py` (`generate_json`).
- Tests run with the fake providers (no API keys).
