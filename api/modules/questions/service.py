"""Business logic for the questions module. Owner: Udith.

Rules:
  * SQL lives in `repository.py`, not here.
  * To use another module, call ITS service (e.g. `from api.modules.syllabus import service`),
    never its repository.
  * AI work goes through `api.core.ai_client` / `api.core.jobs`, never directly to a provider.
"""

import logging
import uuid
from typing import Any

from fastapi import BackgroundTasks, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import jobs, storage
from api.core.ai_client import AIClient
from api.core.errors import AppError, ConflictError, NotFoundError
from api.core.security import CurrentUser
from api.modules.questions import repository
from api.modules.questions.schemas import (
    AdminOption,
    AdminQuestionIn,
    AdminQuestionOut,
    AdminQuestionPage,
    AdminQuestionRow,
    ExplainQuestionResponse,
    ModuleStatus,
    OptionMisconceptionOut,
    PastPaperAnswerIn,
    PastPaperOut,
    PastPaperQuestionOut,
    QuestionDetailOut,
    QuestionOptionOut,
    TopicPracticeQuestionsOut,
)
from api.modules.syllabus import service as syllabus_service
from shared.db.models import (
    AIJob,
    MCQOption,
    Misconception,
    PastPaper,
    PastPaperQuestion,
    Question,
)
from shared.db.session import SessionLocal
from shared.enums import ContentStatus, Difficulty, JobStatus, JobType, QuestionType

logger = logging.getLogger(__name__)

MODULE_NAME = "questions"


async def get_status() -> ModuleStatus:
    """Placeholder used by the status route."""
    return ModuleStatus(module=MODULE_NAME, status="todo")


async def get_example_questions(
    session: AsyncSession, topic_id: uuid.UUID, limit: int = 3
) -> list[dict[str, Any]]:
    """Approved MCQs shown to the AI as style examples when generating a paper."""
    rows = await repository.random_approved_mcqs(session, topic_id, limit)
    examples = []
    for question, options in rows:
        correct = next((o.text for o in options if o.is_correct), None)
        if correct is not None:
            examples.append(
                {
                    "question": question.stem,
                    "options": [o.text for o in options],
                    "correct_answer": correct,
                }
            )
    return examples


async def _visible_question(
    session: AsyncSession, user: CurrentUser, question_id: uuid.UUID
) -> tuple[Question, list[MCQOption]]:
    """A question this student may see: approved (question bank), or one of their own AI
    questions (from their papers). Anything else is "not found", so it isn't leaked."""
    row = await repository.get_by_id(session, question_id)
    if row is not None:
        question = row[0]
        own = question.created_by == user.id
        if question.status == ContentStatus.APPROVED or own or user.is_admin:
            return row
    raise NotFoundError(f"Question '{question_id}' not found", code="QUESTION_NOT_FOUND")


async def get_question(
    session: AsyncSession, user: CurrentUser, question_id: uuid.UUID
) -> QuestionDetailOut:
    """Fetch one question with its MCQ options. The correct answer and the explanation are
    hidden (the explanation gives the answer away); use POST /questions/{id}/explain after
    answering."""
    question, options = await _visible_question(session, user, question_id)
    return QuestionDetailOut(
        id=question.id,
        topic_id=question.topic_id,
        question_type=question.question_type,
        stem=question.stem,
        marks=question.marks,
        options=[QuestionOptionOut(id=o.id, label=o.label, text=o.text) for o in options],
    )


async def list_topic_questions(
    session: AsyncSession, topic_id: uuid.UUID, limit: int = 10
) -> TopicPracticeQuestionsOut:
    """Approved practice questions for a topic."""
    # Verify topic exists
    await syllabus_service.get_topics(session, [topic_id])
    rows = await repository.list_by_topic(session, topic_id, limit=limit)
    questions = [
        QuestionDetailOut(
            id=q.id,
            topic_id=q.topic_id,
            question_type=q.question_type,
            stem=q.stem,
            marks=q.marks,
            options=[QuestionOptionOut(id=o.id, label=o.label, text=o.text) for o in options],
        )
        for q, options in rows
    ]
    return TopicPracticeQuestionsOut(topic_id=topic_id, total=len(questions), questions=questions)


async def explain_question(
    session: AsyncSession,
    user: CurrentUser,
    question_id: uuid.UUID,
    selected_option_id: uuid.UUID | None,
    ai: AIClient,
) -> ExplainQuestionResponse:
    """Explain an MCQ answer using the AI service."""
    question, options = await _visible_question(session, user, question_id)
    correct = next((o.text for o in options if o.is_correct), None) or ""
    selected = next((o.text for o in options if o.id == selected_option_id), None)

    items = [
        {
            "question_id": str(question.id),
            "question": question.stem,
            "correct_answer": correct,
            "selected_option": selected,
        }
    ]
    response = await ai.sync("explain-mcq", {"items": items})
    explanations = response.get("result", {}).get("explanations", {})
    explanation_text = explanations.get(
        str(question.id), question.explanation or "No explanation available."
    )
    return ExplainQuestionResponse(question_id=question.id, explanation=explanation_text)


# =========================================================================== admin: question bank
# Used by admin/questions_admin.py.


def question_code(question: Question) -> str:
    """What admins call a question, e.g. "Q-4821"."""
    return f"Q-{question.number}"


def admin_status(question: Question) -> str:
    return "outdated" if question.is_outdated else question.status.value


def _not_found(question_id: uuid.UUID) -> NotFoundError:
    return NotFoundError(f"Question '{question_id}' not found", code="QUESTION_NOT_FOUND")


async def admin_list_questions(
    session: AsyncSession,
    *,
    unit_number: int | None,
    question_type: str | None,
    difficulty: str | None,
    status: str | None,
    page: int,
    page_size: int,
) -> AdminQuestionPage:
    """Newest first. Without `status` the archived ones (deleted but used) are left out."""
    rows, total, past_paper = await repository.list_bank(
        session,
        unit_number=unit_number,
        question_type=QuestionType(question_type) if question_type else None,
        difficulty=difficulty,
        status=status,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return AdminQuestionPage(
        items=[
            AdminQuestionRow(
                id=r.question.id,
                code=question_code(r.question),
                stem=r.question.stem,
                unit_number=r.unit_number,
                topic_title=r.topic_title,
                type=r.question.question_type.value,  # type: ignore[arg-type]
                difficulty=r.question.difficulty.value,  # type: ignore[arg-type]
                source_year=r.question.year,
                is_ai_generated=r.question.source == "ai",
                status=admin_status(r.question),  # type: ignore[arg-type]
            )
            for r in rows
        ],
        total=total,
        past_paper_percent=round(100 * past_paper / total) if total else 0,
    )


def missing_for_publish(
    question_type: str, stem: str, options: list[AdminOption]
) -> list[dict[str, str]]:
    """Pure: what stops a question from being published. Empty = ready.

    MCQs need text on every option, exactly one correct option and a misconception on every
    wrong one (so a wrong answer can be explained)."""
    problems: list[dict[str, str]] = []
    if not stem.strip():
        problems.append({"field": "stem", "message": "Write the question"})
    if question_type != QuestionType.MCQ.value:
        return problems
    if len(options) < 2:
        problems.append({"field": "options", "message": "An MCQ needs at least 2 options"})
    correct = [o for o in options if o.is_correct]
    if len(correct) != 1:
        problems.append({"field": "options", "message": "Mark exactly one option as correct"})
    for option in options:
        if not option.text.strip():
            problems.append(
                {"field": f"options.{option.label}.text", "message": "Write the option text"}
            )
        if not option.is_correct and not (option.misconception or "").strip():
            problems.append(
                {
                    "field": f"options.{option.label}.misconception",
                    "message": "Say which misconception leads to this wrong answer",
                }
            )
    return problems


def _incomplete(problems: list[dict[str, str]]) -> AppError:
    return AppError(
        "This question can't be published yet: " + "; ".join(p["message"] for p in problems),
        code="QUESTION_INCOMPLETE",
        status_code=422,
        extra={"details": problems},
    )


async def _question_out(session: AsyncSession, question: Question) -> AdminQuestionOut:
    options = (await repository.options_with_misconceptions(session, [question.id]))[question.id]
    return AdminQuestionOut(
        id=question.id,
        code=question_code(question),
        stem=question.stem,
        type=question.question_type.value,  # type: ignore[arg-type]
        difficulty=question.difficulty.value,  # type: ignore[arg-type]
        unit_id=question.unit_id,
        topic_id=question.topic_id,
        concept_id=await repository.main_concept(session, question.id),
        explanation=question.explanation or "",
        status=admin_status(question),  # type: ignore[arg-type]
        is_ai_generated=question.source == "ai",
        options=[
            AdminOption(
                label=o.label,  # type: ignore[arg-type]
                text=o.text,
                is_correct=o.is_correct,
                misconception=title,
            )
            for o, title in options
        ],
    )


async def admin_get_question(session: AsyncSession, question_id: uuid.UUID) -> AdminQuestionOut:
    question = await repository.get_question(session, question_id)
    if question is None:
        raise _not_found(question_id)
    return await _question_out(session, question)


async def _misconception_id(
    session: AsyncSession, concept_id: uuid.UUID | None, text: str | None, admin_id: uuid.UUID
) -> uuid.UUID | None:
    """The misconceptions row for this text (reused when the same one already exists)."""
    title = " ".join((text or "").split())[:200]
    if not title:
        return None
    row = await repository.find_misconception(session, concept_id, title)
    if row is None:
        row = Misconception(
            id=uuid.uuid4(), concept_id=concept_id, title=title, created_by=admin_id
        )
        await repository.add(session, row)
    return row.id


async def _save_options(
    session: AsyncSession, question: Question, options: list[AdminOption], admin_id: uuid.UUID
) -> None:
    """Update the options in place by label, so students' saved answers keep pointing at them.

    Every option is first set to "not correct" and flushed, because the database allows only
    one correct option per question at any moment."""
    existing = {
        o.label: o
        for o, _ in (await repository.options_with_misconceptions(session, [question.id]))[
            question.id
        ]
    }
    if question.question_type != QuestionType.MCQ:
        options = []
    for current in existing.values():
        current.is_correct = False
    await session.flush()
    concept_id = await repository.main_concept(session, question.id)
    wanted = {o.label for o in options}
    for label, old in existing.items():
        if label not in wanted:
            await repository.delete_row(session, old)
    for option in options:
        found = existing.get(option.label)
        if found is None:
            row = MCQOption(id=uuid.uuid4(), question_id=question.id, label=option.label, text="")
            await repository.add(session, row)
        else:
            row = found
        row.text = option.text
        row.is_correct = option.is_correct
        row.misconception_id = (
            None
            if option.is_correct
            else await _misconception_id(session, concept_id, option.misconception, admin_id)
        )
    await session.flush()


async def _apply(
    session: AsyncSession, question: Question, req: AdminQuestionIn, admin_id: uuid.UUID
) -> None:
    if req.status == "approved":
        problems = missing_for_publish(req.type, req.stem, req.options)
        if problems:
            raise _incomplete(problems)
    place = await syllabus_service.check_placement(
        session, req.unit_id, req.topic_id, req.concept_id
    )
    question.stem = req.stem.strip()
    question.question_type = QuestionType(req.type)
    question.difficulty = Difficulty(req.difficulty)
    question.unit_id, question.topic_id = place.unit_id, place.topic_id
    question.explanation = (req.explanation or "").strip() or None
    question.status = ContentStatus(req.status)
    if question.source != "past_paper":
        question.source = "ai" if req.is_ai_generated else "admin"
    await repository.set_concept(session, question.id, place.concept_id)
    await _save_options(session, question, req.options, admin_id)


async def admin_create_question(
    session: AsyncSession, admin_id: uuid.UUID, req: AdminQuestionIn
) -> AdminQuestionOut:
    question = Question(
        id=uuid.uuid4(),
        question_type=QuestionType(req.type),
        stem=req.stem,
        source="admin",
        marks=1,
        created_by=admin_id,
    )
    await repository.add(session, question)  # gets its number (Q-....) from Postgres
    await _apply(session, question, req, admin_id)
    await session.commit()
    await session.refresh(question)
    return await _question_out(session, question)


async def admin_update_question(
    session: AsyncSession, admin_id: uuid.UUID, question_id: uuid.UUID, req: AdminQuestionIn
) -> AdminQuestionOut:
    question = await repository.get_question(session, question_id)
    if question is None:
        raise _not_found(question_id)
    await _apply(session, question, req, admin_id)
    await session.commit()
    await session.refresh(question)
    return await _question_out(session, question)


async def _ready_to_publish(session: AsyncSession, questions: list[Question]) -> None:
    """422 QUESTION_INCOMPLETE (with every problem) if any question can't be published."""
    options = await repository.options_with_misconceptions(session, [q.id for q in questions])
    problems = []
    for q in questions:
        mapped = [
            AdminOption(label=o.label, text=o.text, is_correct=o.is_correct, misconception=t)  # type: ignore[arg-type]
            for o, t in options[q.id]
        ]
        for p in missing_for_publish(q.question_type.value, q.stem, mapped):
            problems.append({"field": f"{question_code(q)}.{p['field']}", "message": p["message"]})
    if problems:
        raise _incomplete(problems)


async def admin_bulk(session: AsyncSession, ids: list[uuid.UUID], action: str) -> None:
    """approve | mark_outdated | delete. All or nothing; 404 QUESTION_NOT_FOUND if any id is
    unknown. `delete` removes unused questions and archives ones students answered."""
    ids = list(dict.fromkeys(ids))
    questions = await repository.get_questions(session, ids)
    missing = sorted(str(i) for i in set(ids) - {q.id for q in questions})
    if missing:
        raise NotFoundError(
            f"Unknown question id(s): {', '.join(missing)}", code="QUESTION_NOT_FOUND"
        )
    if action == "approve":
        await _ready_to_publish(session, questions)
        for q in questions:
            q.status = ContentStatus.APPROVED
            q.is_outdated = False
    elif action == "mark_outdated":
        for q in questions:
            q.is_outdated = True
    else:
        used = await repository.used_question_ids(session, ids)
        for q in questions:
            if q.id in used:
                q.status = ContentStatus.ARCHIVED  # keeps students' answers and papers intact
            else:
                await repository.delete_row(session, q)
    await session.commit()


async def admin_set_review_status(
    session: AsyncSession, question_id: uuid.UUID, approve: bool
) -> Question:
    """Approve (checked like publishing) or reject one question. Used by the quality review."""
    question = await repository.get_question(session, question_id)
    if question is None:
        raise _not_found(question_id)
    if approve:
        await _ready_to_publish(session, [question])
    question.status = ContentStatus.APPROVED if approve else ContentStatus.REJECTED
    return question


async def option_counts(
    session: AsyncSession, question_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, int]]:
    """{question_id: (options, correct options)} - for the quality checks."""
    rows = await repository.options_with_misconceptions(session, question_ids)
    return {
        qid: (len(options), sum(1 for o, _ in options if o.is_correct))
        for qid, options in rows.items()
    }


# =========================================================================== admin: past papers
# Upload -> EXTRACT_PAST_PAPER job (ai_service/pipelines/questions/past_paper_extract.py) in the
# background -> past_paper_questions rows. Progress: 0 queued, 0.2 reading, 0.9 saving, 1 done.

MAX_PAST_PAPER_BYTES = 40 * 1024 * 1024  # 40 MB
LOW_CONFIDENCE = 0.8
PDF_MIME = "application/pdf"


def _extraction(paper: PastPaper, low: int) -> str:
    if paper.extraction_status == "failed":
        return "failed"
    if paper.extraction_status == "done":
        return "low_confidence" if low else "done"
    return "running"  # queued or running


def past_paper_out(paper: PastPaper, extracted: int, low: int) -> PastPaperOut:
    return PastPaperOut(
        id=paper.id,
        year=paper.year,
        paper_type=paper.paper_type,  # type: ignore[arg-type]
        scheme_linked=paper.scheme_path is not None,
        extraction=_extraction(paper, low),  # type: ignore[arg-type]
        questions_extracted=extracted,
        progress=round(paper.progress, 2),
        low_confidence=low,
        outdated_syllabus=paper.outdated_syllabus,
    )


def _paper_question_out(q: PastPaperQuestion) -> PastPaperQuestionOut:
    return PastPaperQuestionOut(
        id=q.id,
        label=q.label,
        marks=q.marks,
        text=q.text,
        ocr_confidence=q.ocr_confidence,
        model_answer=q.model_answer,
        keywords=list(q.keywords or []),
        suggested_keywords=list(q.suggested_keywords or []),
    )


async def read_pdf_upload(file: UploadFile) -> bytes:
    """The bytes of an uploaded PDF. Checked by its content, because Flutter web sends PDFs
    as "application/octet-stream". 413 FILE_TOO_LARGE · 415 UNSUPPORTED_FILE_TYPE · 422."""
    data = await file.read(MAX_PAST_PAPER_BYTES + 1)  # never read more than the limit
    if len(data) > MAX_PAST_PAPER_BYTES:
        raise AppError("The file is larger than 40 MB", code="FILE_TOO_LARGE", status_code=413)
    if not data:
        raise AppError("The file is empty", code="EMPTY_FILE", status_code=422)
    if not data.startswith(b"%PDF-"):
        raise AppError("Only PDF files are accepted", code="UNSUPPORTED_FILE_TYPE", status_code=415)
    return data


async def admin_list_past_papers(session: AsyncSession) -> list[PastPaperOut]:
    rows = await repository.list_past_papers(session, LOW_CONFIDENCE)
    return [past_paper_out(p, n, low) for p, n, low in rows]


async def admin_upload_past_paper(
    session: AsyncSession,
    admin_id: uuid.UUID,
    *,
    file: UploadFile,
    year: int,
    paper_type: str,
    scheme: UploadFile | None,
    ai: AIClient,
    background_tasks: BackgroundTasks,
) -> PastPaperOut:
    """Save the PDF (+ marking scheme), then extract the questions in the background.

    409 PAST_PAPER_EXISTS when that year + paper type was uploaded already."""
    if await repository.past_paper_exists(session, year, paper_type):
        raise ConflictError(
            f"The {year} {paper_type.replace('_', ' ')} paper is already uploaded",
            code="PAST_PAPER_EXISTS",
        )
    data = await read_pdf_upload(file)
    scheme_data = await read_pdf_upload(scheme) if scheme is not None else None

    paper_id = uuid.uuid4()
    file_path = f"past_papers/{paper_id}.pdf"
    await run_in_threadpool(storage.upload_bytes, file_path, data, PDF_MIME)
    scheme_path = None
    if scheme_data is not None:
        scheme_path = f"past_papers/{paper_id}-scheme.pdf"
        await run_in_threadpool(storage.upload_bytes, scheme_path, scheme_data, PDF_MIME)

    paper = PastPaper(
        id=paper_id,
        year=year,
        paper_type=paper_type,
        file_name=(file.filename or "paper.pdf")[:255],
        file_path=file_path,
        size_bytes=len(data),
        scheme_path=scheme_path,
        extraction_status="queued",
        progress=0.0,
        outdated_syllabus=False,
        uploaded_by=admin_id,
    )
    await repository.add(session, paper)
    payload = {"past_paper_id": str(paper_id), "file_path": file_path, "paper_type": paper_type}
    job = await jobs.create_job(session, JobType.EXTRACT_PAST_PAPER, payload, requested_by=admin_id)
    paper.job_id = job.id
    await session.commit()
    background_tasks.add_task(process_past_paper, paper_id, job.id, ai)
    return past_paper_out(paper, 0, 0)


async def run_extraction(session: AsyncSession, paper: PastPaper, job: AIJob, ai: AIClient) -> None:
    """Run the job and save the questions in the same commit as "succeeded"."""
    paper.extraction_status = "running"
    paper.progress = 0.2
    await session.commit()

    async def save(done: AIJob) -> None:
        found = ((done.result or {}).get("result") or {}).get("questions") or []
        paper.progress = 0.9
        rows = [
            PastPaperQuestion(
                past_paper_id=paper.id,
                position=n,
                label=str(q.get("label") or f"Q{n}")[:30],
                marks=q.get("marks"),
                text=str(q.get("text") or ""),
                ocr_confidence=q.get("ocr_confidence"),
                suggested_keywords=[str(k)[:100] for k in q.get("suggested_keywords") or []],
                keywords=[],
            )
            for n, q in enumerate(found, start=1)
        ]
        await repository.replace_past_paper_questions(session, paper.id, rows)
        paper.extraction_status = "done"
        paper.progress = 1.0
        paper.error = None

    job = await jobs.run_job_inline(session, job, ai, on_success=save)
    if job.status == JobStatus.FAILED:
        paper.extraction_status = "failed"
        paper.error = job.error
        await session.commit()


async def process_past_paper(paper_id: uuid.UUID, job_id: uuid.UUID, ai: AIClient) -> None:
    """Background task: extract one paper. Uses its own DB session."""
    async with SessionLocal() as session:
        paper = await repository.get_past_paper(session, paper_id)
        job = await session.get(AIJob, job_id)
        if paper is None or job is None:
            logger.error("Past paper %s or job %s not found", paper_id, job_id)
            return
        await run_extraction(session, paper, job, ai)


async def admin_past_paper_questions(
    session: AsyncSession, paper_id: uuid.UUID
) -> list[PastPaperQuestionOut]:
    """404 PAST_PAPER_NOT_FOUND."""
    if await repository.get_past_paper(session, paper_id) is None:
        raise NotFoundError("Past paper not found", code="PAST_PAPER_NOT_FOUND")
    return [
        _paper_question_out(q)
        for q in await repository.list_past_paper_questions(session, paper_id)
    ]


async def admin_save_past_paper_answer(
    session: AsyncSession, question_id: uuid.UUID, req: PastPaperAnswerIn
) -> PastPaperQuestionOut:
    """404 PAST_PAPER_QUESTION_NOT_FOUND."""
    question = await repository.get_past_paper_question(session, question_id)
    if question is None:
        raise NotFoundError("Past paper question not found", code="PAST_PAPER_QUESTION_NOT_FOUND")
    question.model_answer = (req.model_answer or "").strip() or None
    question.keywords = req.keywords
    await session.commit()
    return _paper_question_out(question)


async def admin_get_past_paper(session: AsyncSession, paper_id: uuid.UUID) -> PastPaperOut | None:
    paper = await repository.get_past_paper(session, paper_id)
    if paper is None:
        return None
    n, low = await repository.past_paper_counts(session, paper_id, LOW_CONFIDENCE)
    return past_paper_out(paper, n, low)


async def question_briefs(
    session: AsyncSession, question_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[str, str]]:
    """{question_id: (code "Q-1042", stem)} - for other admin screens."""
    if not question_ids:
        return {}
    return {
        q.id: (question_code(q), q.stem)
        for q in await repository.get_questions(session, list(set(question_ids)))
    }


async def admin_set_option_misconception(
    session: AsyncSession, admin_id: uuid.UUID, option_id: uuid.UUID, text: str | None
) -> OptionMisconceptionOut:
    """Link a wrong option to the misconception behind it (MCQ mapping).

    404 OPTION_NOT_FOUND · 422 CORRECT_OPTION_NO_MISCONCEPTION (the right answer has none)."""
    option = await repository.get_option(session, option_id)
    if option is None:
        raise NotFoundError("Option not found", code="OPTION_NOT_FOUND")
    text = " ".join((text or "").split()) or None
    if option.is_correct and text:
        raise AppError(
            "The correct option can't have a misconception",
            code="CORRECT_OPTION_NO_MISCONCEPTION",
            status_code=422,
        )
    concept_id = await repository.main_concept(session, option.question_id)
    option.misconception_id = await _misconception_id(session, concept_id, text, admin_id)
    await session.commit()
    question = await repository.get_question(session, option.question_id)
    assert question is not None  # options are deleted with their question
    return OptionMisconceptionOut(
        option_id=option.id,
        question_id=question.id,
        question_code=question_code(question),
        label=option.label,
        text=option.text,
        is_correct=option.is_correct,
        misconception=await repository.misconception_title(session, option.misconception_id),
    )
