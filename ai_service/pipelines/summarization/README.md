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
| `summarize.py` | Map-reduce summary of an upload. | `SUMMARIZE_UPLOAD` | - |

## Rules

- Call AI only through `ai_service.providers` (`get_llm()`, `get_embedder()`, ...). Never import an SDK here.
- Grounded pipelines use `ai_service.rag.retrieval.retriever.retrieve` + `ai_service.rag.context_builder.build_context`.
  Never query `document_chunks` directly.
- Prompts live in `ai_service/prompts/summarization/` and are versioned (`name.v1.j2`). Return the prompt id with the result.
- Validate LLM output with a schema from `ai_service/schemas/llm_outputs.py` (`generate_json`).
- Tests run with the fake providers (no API keys).
