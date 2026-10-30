# `pipelines/home`

| | |
|---|---|
| **Owner** | Samni |
| **Purpose** | AI text for the home dashboard |

| File | What it does | Called by | Uses RAG |
|---|---|---|---|
| `next_action.py` | One sentence: why revising the weakest unit/topic is the best next step (prompt `home/next_action.v1`) | `POST /sync/next-action` ← api `home.service` | - |

The api falls back to a template sentence (`ai_generated: false`) if this call fails.
TODO(Samni): use recent mistakes (performance) for a more specific reason; cache it per day.
