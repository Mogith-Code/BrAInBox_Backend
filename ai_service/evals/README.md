# AI evaluations (`ai_service/evals/`)

Offline checks that tell us whether a prompt, model or retrieval change made things **better or worse**,
before it reaches students. Unit tests check that code runs. Evals check that the AI output is good.

| Eval | Owner | Data (in `data/`) | Metric |
|---|---|---|---|
| RAG retrieval | Samni | `rag_queries.jsonl` – query + expected chunk/topic | recall@k, MRR |
| Notes grounding | Samni | topics + approved notes | % of claims with a valid citation |
| MCQ quality | Udith | reviewed MCQs | reviewer agreement with admins |
| Answer marking | Keshomigha | answers with manual marks | mean absolute error vs. manual marks |
| Moderation | Mogith | labelled posts | precision / recall on flagged posts |

Run:

```bash
python -m ai_service.evals.run_eval --name rag
```

Rules:
- Eval data must not contain real student names or personal data.
- Record the prompt version and model name with every eval result. Compare like with like.
