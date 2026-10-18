# `pipelines/visuals`

| | |
|---|---|
| **Owner** | Mogith |
| **Purpose** | Choose and create visuals (Mermaid diagrams or images) for concepts. |
| **Branch** | `feature/ai-visuals` |

| File | What it does | Job type | Uses RAG |
|---|---|---|---|
| `decide_visual.py` | Decide which kind of visual fits a concept, then build it. | `GENERATE_VISUAL` | - |
| `diagram_mermaid.py` | Check and clean Mermaid code produced by the LLM. | - | - |
| `illustration.py` | Generate an illustration image and store it. | - | - |

## Rules

- Call AI only through `ai_service.providers` (`get_llm()`, `get_embedder()`, ...). Never import an SDK here.
- Grounded pipelines use `ai_service.rag.retrieval.retriever.retrieve` + `ai_service.rag.context_builder.build_context`.
  Never query `document_chunks` directly.
- Prompts live in `ai_service/prompts/visuals/` and are versioned (`name.v1.j2`). Return the prompt id with the result.
- Validate LLM output with a schema from `ai_service/schemas/llm_outputs.py` (`generate_json`).
- Tests run with the fake providers (no API keys).
