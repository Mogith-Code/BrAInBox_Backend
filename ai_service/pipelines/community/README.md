# `pipelines/community`

| | |
|---|---|
| **Owner** | Mogith |
| **Purpose** | AI help for the community: tags, moderation and suggested answers. |
| **Branch** | `feature/ai-community` |

| File | What it does | Job type | Uses RAG |
|---|---|---|---|
| `auto_tag.py` | Suggest tags + unit for a post (fast sync call). | - | - |
| `suggested_answer.py` | Draft an AI answer to a student question (RAG-grounded). | `SUGGEST_ANSWER` | yes |
| `moderation.py` | Check a post for unsafe content. | `MODERATE_POST` | - |

## Rules

- Call AI only through `ai_service.providers` (`get_llm()`, `get_embedder()`, ...). Never import an SDK here.
- Grounded pipelines use `ai_service.rag.retrieval.retriever.retrieve` + `ai_service.rag.context_builder.build_context`.
  Never query `document_chunks` directly.
- Prompts live in `ai_service/prompts/community/` and are versioned (`name.v1.j2`). Return the prompt id with the result.
- Validate LLM output with a schema from `ai_service/schemas/llm_outputs.py` (`generate_json`).
- Tests run with the fake providers (no API keys).
