# `pipelines/questions`

| | |
|---|---|
| **Owner** | Udith |
| **Purpose** | Generate, review and assemble questions (RAG-grounded). |
| **Branch** | `feature/ai-questions` |

| File | What it does | Job type | Uses RAG |
|---|---|---|---|
| `mcq_mapping.py` | Map wrong MCQ options to misconceptions. | `MAP_MISCONCEPTIONS` | - |
| `generate_questions.py` | Generate A/L-style MCQs for a topic. | `GENERATE_QUESTIONS` | yes |
| `quality_checks.py` | Rule checks + LLM reviewer for generated questions. | `REVIEW_QUESTIONS` | yes |
| `paper_builder.py` | Assemble a model paper from approved questions. | `BUILD_PAPER` | - |

## Rules

- Call AI only through `ai_service.providers` (`get_llm()`, `get_embedder()`, ...). Never import an SDK here.
- Grounded pipelines use `ai_service.rag.retrieval.retriever.retrieve` + `ai_service.rag.context_builder.build_context`.
  Never query `document_chunks` directly.
- Prompts live in `ai_service/prompts/questions/` and are versioned (`name.v1.j2`). Return the prompt id with the result.
- Validate LLM output with a schema from `ai_service/schemas/llm_outputs.py` (`generate_json`).
- Tests run with the fake providers (no API keys).
