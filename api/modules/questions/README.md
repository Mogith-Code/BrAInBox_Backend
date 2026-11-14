# `questions` module

| | |
|---|---|
| **Owner** | Udith |
| **Purpose** | Question bank: questions, MCQ options and misconceptions (read side for students). |
| **Tables** | `questions`, `mcq_options`, `misconceptions`, `question_concepts` |
| **Jira epic** | BRN-E06 Question Bank *(placeholder key – replace with the real one)* |
| **Git branch** | `feature/questions` (tasks: `feature/questions/BRN-xx-short-name`) |

## Endpoints

| Method | Path | Status | Description |
|---|---|---|---|
| GET | `/api/v1/questions/{id}` | ✅ done | One question with options (no answer key, no explanation). Approved questions, or the student's own AI ones |
| GET | `/api/v1/topics/{id}/questions` | ✅ done | Practice questions for a topic |
| POST | `/api/v1/questions/{id}/explain` | ✅ done | Explain an MCQ answer (sync AI call) |


Placeholder right now: `GET /api/v1/questions/status` → `{"module": "questions", "status": "todo"}` (needs login).

## Files

| File | What goes in it |
|---|---|
| `router.py` | HTTP endpoints only (validate, check role, call service) |
| `schemas.py` | Pydantic request/response models |
| `service.py` | Business logic |
| `repository.py` | All SQL queries for this module |

Models live in `shared/db/models/`. Call other modules through their `service.py`, never their `repository.py`.
Tests: `tests/api/test_questions.py`.

## Admin question bank (`admin/questions_admin.py`)

`service.admin_list_questions / admin_get_question / admin_create_question / admin_update_question / admin_bulk`.
- `questions.number` (IDENTITY from 1000, migration `0007_question_bank_codes`) gives the code `Q-1042`.
- `questions.is_outdated` = admin "Mark outdated"; outdated questions are hidden from students.
- `missing_for_publish()` is the publish rule (one correct option, a misconception on every wrong one).
- Tests: `tests/api/test_admin_questions.py`.

## Admin MCQ mapping

`PUT /admin/options/{option_id}/misconception` (`service.admin_set_option_misconception`, the second router
`options_router` in `admin/questions_admin.py`). Tests: `tests/api/test_admin_mcq_mapping.py`.

## Admin past papers

Tables `past_papers` + `past_paper_questions` (`shared/db/models/past_paper.py`, migration `0008_past_papers`).
`service.admin_upload_past_paper` stores the PDF, creates an EXTRACT_PAST_PAPER job and runs it after the response
(`process_past_paper`); the questions are saved in the same commit as the job's success. Tests mock OCR:
`tests/api/test_admin_past_papers.py`.
