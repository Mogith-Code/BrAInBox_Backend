# `pipelines/recommendations`

| | |
|---|---|
| **Owner** | Udith |
| **Purpose** | Rank learning resources for a student's weak concepts. |
| **Branch** | `feature/ai-recommendations` |

| File | What it does | Job type | Uses RAG |
|---|---|---|---|
| `rank_resources.py` | Rank candidate resources (e.g. YouTube results) for weak concepts. | `RANK_RESOURCES` | - |

## Rules

- Call AI only through `ai_service.providers` (`get_llm()`, `get_embedder()`, ...). Never import an SDK here.
- Grounded pipelines use `ai_service.rag.retrieval.retriever.retrieve` + `ai_service.rag.context_builder.build_context`.
  Never query `document_chunks` directly.
- Prompts live in `ai_service/prompts/recommendations/` and are versioned (`name.v1.j2`). Return the prompt id with the result.
- Validate LLM output with a schema from `ai_service/schemas/llm_outputs.py` (`generate_json`).
- Tests run with the fake providers (no API keys).
