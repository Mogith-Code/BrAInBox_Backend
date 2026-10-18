# `pipelines/notes`

| | |
|---|---|
| **Owner** | Samni |
| **Purpose** | Generate topic notes grounded in approved sources (RAG). |
| **Branch** | `feature/ai-notes` |

| File | What it does | Job type | Uses RAG |
|---|---|---|---|
| `generate_notes.py` | Generate full notes for a topic. | `GENERATE_NOTES` | yes |
| `short_notes.py` | Generate short revision notes for a topic. | `GENERATE_SHORT_NOTES` | yes |

## Rules

- Call AI only through `ai_service.providers` (`get_llm()`, `get_embedder()`, ...). Never import an SDK here.
- Grounded pipelines use `ai_service.rag.retrieval.retriever.retrieve` + `ai_service.rag.context_builder.build_context`.
  Never query `document_chunks` directly.
- Prompts live in `ai_service/prompts/notes/` and are versioned (`name.v1.j2`). Return the prompt id with the result.
- Validate LLM output with a schema from `ai_service/schemas/llm_outputs.py` (`generate_json`).
- Tests run with the fake providers (no API keys).
