# `exams` module

| | |
|---|---|
| **Owner** | Udith |
| **Purpose** | Full papers (past papers and AI-built model papers) and timed attempts. Paper generation + evaluation ported from Udith's original `Paper_genaration_and_evaluation` branch. |
| **Tables** | `papers`, `paper_questions`, `attempts`, `responses` |
| **Jira epic** | BRN-E08 Exams & Past Papers *(placeholder key – replace with the real one)* |
| **Git branch** | `feature/exams` (tasks: `feature/exams/BRN-xx-short-name`) |

## Endpoints

| Method | Path | Status | Description |
|---|---|---|---|
| POST | `/api/v1/papers/generate` | ✅ done | AI model paper for 1–10 topics (BUILD_PAPER job, run inline) |
| POST | `/api/v1/papers/{id}/submit` | ✅ done | Mark answers ("A".."E"), score per topic, weak topics, AI explanations; saves an attempt |
| GET | `/api/v1/papers` | planned | List papers |
| GET | `/api/v1/papers/{id}` | planned | One paper |
| POST | `/api/v1/attempts` | planned | Start a timed attempt |
| GET | `/api/v1/attempts/{id}` | planned | Attempt with answers |

### How paper generation works

1. `syllabus.service.get_topics` checks the topic ids; `questions.service.get_example_questions` adds up to 3
   approved MCQs per topic as style examples.
2. A `BUILD_PAPER` job is created and run right away (`core/jobs.run_job_inline`). The ai_service
   (`pipelines/questions/paper_builder.py`) splits the questions across topics, retrieves syllabus context (RAG)
   and generates MCQs with prompt `questions/generate_mcq.v2`. A topic without syllabus content becomes a warning.
3. The questions are saved as real `questions` + `mcq_options` rows (`source=ai`, `status=pending_review`) in a
   `papers` row with `paper_type=ai_generated`, owned by the student. Answers are not returned
   (set `DEBUG_SHOW_ANSWERS=true` in dev to see them).

### How marking works

`service.evaluate_paper` (Udith's evaluator, unchanged logic) marks every question, scores each topic and lists
topics under 55 % (grade S or F, from `performance/grading.py`) as weak. Wrong answers get 1–2 sentence explanations from the ai_service (`/sync/explain-mcq`).
If that call fails, marking still works and there are no explanations. The attempt and one `responses` row per
question are saved.

Seed example questions: `python scripts/import_question_bank.py` (reads `data/questions/question_bank.json`).

## Files

| File | What goes in it |
|---|---|
| `router.py` | HTTP endpoints only (validate, check role, call service) |
| `schemas.py` | Pydantic request/response models |
| `service.py` | Business logic |
| `repository.py` | All SQL queries for this module |

Models live in `shared/db/models/`. Call other modules through their `service.py`, never their `repository.py`.
Tests: `tests/api/test_exams.py`.
