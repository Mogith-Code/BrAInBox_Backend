# `exams` module

| | |
|---|---|
| **Owner** | Udith |
| **Purpose** | Full papers (past papers and AI-built model papers from a blueprint), marking (MCQ + written) and timed attempts. Paper generation + evaluation ported from Udith's original `Paper_genaration_and_evaluation` branch. |
| **Tables** | `papers`, `paper_questions`, `attempts`, `responses` |
| **Jira epic** | BRN-E08 Exams & Past Papers *(placeholder key – replace with the real one)* |
| **Git branch** | `feature/exams` (tasks: `feature/exams/BRN-xx-short-name`) |

## Endpoints

| Method | Path | Status | Description |
|---|---|---|---|
| GET | `/api/v1/papers?year=&type=&page=&size=` | ✅ done | Approved past papers, newest year first. `type` = `mcq` / `structured` / `essay`: papers with that kind of question. Each row has `question_count` and `outdated_count` |
| GET | `/api/v1/papers/{id}?hide_outdated=false` | ✅ done | An approved past paper or one of my model papers: questions in order, no answers. Every question has `is_outdated` (the question, its topic or its unit is outdated); `hide_outdated=true` leaves them out (`hidden_outdated` = how many) |
| POST | `/api/v1/papers/generate` | ✅ done | Model paper from a **blueprint** → **202** `{job_id, from_bank, to_generate}`; poll `GET /jobs/{job_id}` for `result.paper_id` |
| POST | `/api/v1/papers/generate-by-units` | ✅ done | AI MCQ paper for 1–10 units (BUILD_PAPER job, run inline, synchronous) |
| POST | `/api/v1/papers/{id}/submit` | ✅ done | MCQs marked at once ("A".."E"), score per topic, weak topics, AI explanations. Structured / essay answers (`answer_text`) are marked in the background by the evaluation module |
| POST | `/api/v1/attempts` | planned | Start a timed attempt |
| GET | `/api/v1/attempts/{id}` | planned | Attempt with answers |

Old URLs of Udith's standalone app (`/exam/generate-paper`, `/exam/generate-paper-by-units`, `/exam/evaluate`) still
work, hidden from `/docs`. `/exam/generate-paper` stays **synchronous** (topics → MCQs, the paper in the response).

Errors: 404 `PAPER_NOT_FOUND` (unknown, an unapproved past paper, or another student's model paper) ·
404 `TOPIC_NOT_FOUND` / `UNIT_NOT_FOUND` · 429 `DAILY_LIMIT_REACHED`.

### Model paper blueprint (`POST /papers/generate`)

```json
{
  "unit_numbers": [2, 6],
  "topic_ids": [],
  "mcq_count": 20, "structured_count": 2, "essay_count": 1,
  "difficulty": {"easy": 0.3, "medium": 0.5, "hard": 0.2},
  "time_limit_minutes": 120,
  "title": "Model paper: Units 2 & 6"
}
```

* Scope: `unit_numbers` and/or `topic_ids` (at least one). With topics, bank questions are taken from those topics
  and gaps are generated per topic; otherwise per unit.
* Counts: MCQ 0–60, structured 0–10, essay 0–6. The old body `{topic_ids, num_questions}` still works and means
  `num_questions` MCQs (20 if no count is given).
* `difficulty`: any non-negative shares (normalised); each type's count is split by largest remainder
  (`service.split_by_mix`, e.g. 10 → 3 / 5 / 2).
* `time_limit_minutes` (10–240) is saved as the paper's `duration_minutes`.

How it is built:

1. For every (type, difficulty) slot, **unseen** approved bank questions come first
   (`questions.service.pick_unseen_bank_questions`): approved, not outdated (question, topic or unit), never
   answered by this student, in scope, random order. MCQs need a correct option; written ones need an approved
   marking scheme (`knowledge_base.service.questions_with_marking_scheme`), otherwise they couldn't be marked.
2. Only the **gaps** go to the AI: one `BUILD_PAPER` job with `{"gaps": [{question_type, difficulty, count, title,
   unit_id, topic_id}], "existing": [bank stems]}`, queued with `jobs.enqueue_job` (202 + job id). Gaps are spread
   over the units / topics (`service.plan_gaps`).
3. The ai_service (`pipelines/questions/paper_builder.build_from_gaps`) generates MCQs with
   `questions/generate_mcq.v3` (v2 + difficulty) and structured / essay questions with a model answer and marking
   points (`questions/generate_written.v1`, `generate_written.py`), all grounded in approved sources (RAG). Every
   question goes through the quality gates (MCQ: rules, blind review, duplicates, syllabus; written: rules +
   duplicates). **A rejected question is regenerated once; if the new one is rejected too it is dropped** with a
   warning, so a paper can come back a little short.
4. `service.on_paper_built` (the BUILD_PAPER job handler) saves the paper in the job's commit: bank questions + the
   generated ones (`source=ai`, `status=pending_review`, with their difficulty), MCQs first, then structured, then
   essay (`paper_type=ai_generated`, owned by the student). A generated written question's model answer and points
   are saved as an AI model answer (`knowledge_base.service.save_ai_marking_scheme`, source `ai`, pending review).
   The job result becomes `{paper_id, title, total_questions, from_bank, generated, warnings}`.
   No question at all → the job fails with `NO_QUESTIONS_GENERATED`.

### Daily limit

`PAPERS_DAILY_LIMIT` (default 5, 0 = off): papers a student may generate in 24 hours. Every `BUILD_PAPER` job of
theirs counts (blueprint, topic and unit papers, old URL), failed ones don't; admins have no limit.
429 `DAILY_LIMIT_REACHED`.

### How marking works

`service.evaluate_paper` (Udith's evaluator, unchanged logic) marks every **MCQ**, scores each topic and lists
topics under 55 % (grade S or F, from `performance/grading.py`) as weak. Wrong answers get 1–2 sentence explanations
from the ai_service (`/sync/explain-mcq`); if that call fails, marking still works without them.

**Structured / essay answers** (`{"question_id", "answer_text"}`) are marked by the evaluation module
(`evaluation.service.start_paper_answer_evaluation`, an `EVALUATE_ANSWER` job linked to the response). The question's
approved marking scheme is used, or the AI one for the student's own generated questions. The response lists them
in `written` (`queued` with `evaluation_id` → `GET /evaluations/{id}`, `unanswered` = 0 marks, `not_markable` = no
marking scheme yet). The attempt is `submitted` until they are all marked; `service.on_paper_answer_marked` (a job
listener) stores each answer's marks on its response and adds them to the attempt's score, then sets it `graded`
(a failed evaluation counts 0). `marks_obtained` / `percent` / `by_topic` in the submit response cover the MCQs;
`written_marks_total` and `pending_written` describe the rest. Evaluation daily limits don't apply to paper answers.

Seed example questions: `python scripts/import_question_bank.py`; past papers: `python scripts/import_past_papers.py`
(see `data/questions/README.md`).

## Files

| File | What goes in it |
|---|---|
| `router.py` | HTTP endpoints only (validate, check role, call service) |
| `schemas.py` | Pydantic request/response models |
| `service.py` | Business logic |
| `repository.py` | All SQL queries for this module |

Models live in `shared/db/models/`. Call other modules through their `service.py`, never their `repository.py`.
Tests: `tests/api/test_exams.py`.
