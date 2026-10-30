# `pipelines/diagnostic`

| | |
|---|---|
| **Owner** | Udith |
| **Purpose** | AI text for the onboarding diagnostic test |

| File | What it does | Called by | Uses RAG |
|---|---|---|---|
| `summary.py` | 2 encouraging sentences: strongest unit + unit that needs work (prompt `diagnostic/summary.v1`) | `POST /sync/diagnostic-summary` ← api `quizzes.service.submit_diagnostic` | - |

The api falls back to a template sentence (`summary_ai_generated: false`) if this call fails.
Works with the fake LLM (`DiagnosticSummary.fake_example`).
