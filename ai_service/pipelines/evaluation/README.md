# `pipelines/evaluation`

| | |
|---|---|
| **Owner** | Keshomigha |
| **Purpose** | Estimate marks and write feedback for written answers. |
| **Branch** | `feature/ai-evaluation` |

| File | What it does | Job type | Uses RAG |
|---|---|---|---|
| `keyword_match.py` | Score an answer by matching marking-scheme keywords. | - | - |
| `semantic_match.py` | Match answer sentences to answer points by meaning (embeddings). | - | - |
| `scorer.py` | Combine keyword + semantic matches into estimated marks. | `EVALUATE_ANSWER` | - |
| `ocr.py` | Read a handwritten answer photo. | `OCR_ANSWER` | - |
| `feedback.py` | Write student-friendly feedback grounded in marking schemes. | - | yes |

## Rules

- Call AI only through `ai_service.providers` (`get_llm()`, `get_embedder()`, ...). Never import an SDK here.
- Grounded pipelines use `ai_service.rag.retrieval.retriever.retrieve` + `ai_service.rag.context_builder.build_context`.
  Never query `document_chunks` directly.
- Prompts live in `ai_service/prompts/evaluation/` and are versioned (`name.v1.j2`). Return the prompt id with the result.
- Validate LLM output with a schema from `ai_service/schemas/llm_outputs.py` (`generate_json`).
- Tests run with the fake providers (no API keys).
