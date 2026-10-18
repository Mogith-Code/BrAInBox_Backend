# `pipelines/questions`

| | |
|---|---|
| **Owner** | Udith |
| **Purpose** | Generate, review and assemble questions (RAG-grounded). Generation, paper building and explanations are ported from Udith's original branch. |
| **Branch** | `feature/ai-questions` |

| File | What it does | Job type | Uses RAG |
|---|---|---|---|
| `mcq_mapping.py` | Map wrong MCQ options to misconceptions. | `MAP_MISCONCEPTIONS` | - |
| `generate_questions.py` | Generate A/L-style MCQs for a topic (prompt `generate_mcq.v2`, retries invalid output). | `GENERATE_QUESTIONS` | yes |
| `quality_checks.py` | Rule checks + LLM reviewer for generated questions. | `REVIEW_QUESTIONS` | yes |
| `paper_builder.py` | Split a paper across topics and generate MCQs for each (failed topics become warnings). | `BUILD_PAPER` | yes |
| `explain_answers.py` | 1–2 sentence feedback for wrong answers (used by `/sync/explain-mcq`). | sync | yes |

## Rules

- Call AI only through `ai_service.providers` (`get_llm()`, `get_embedder()`, ...). Never import an SDK here.
- Grounded pipelines use `ai_service.rag.retrieval.retriever.retrieve` + `ai_service.rag.context_builder.build_context`.
  Never query `document_chunks` directly.
- Prompts live in `ai_service/prompts/questions/` and are versioned (`name.v1.j2`). Return the prompt id with the result.
- Validate LLM output with a schema from `ai_service/schemas/llm_outputs.py` (`generate_json`).
- Tests run with the fake providers (no API keys).
