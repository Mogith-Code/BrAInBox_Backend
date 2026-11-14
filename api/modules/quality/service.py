"""Business logic for the quality module. Owner: Udith.

Admin quality review (admin/questions_admin.py):
  * The queue = AI-generated questions waiting for review (draft / pending_review).
  * Four checks per question. The AI reviewer (REVIEW_QUESTIONS job, pipeline
    ai_service/pipelines/questions/quality_checks.py) saves its result in
    `question_reviews.checks`; we show the newest AI review. Until the AI has checked a
    question, "Single correct answer" and "Duplicate check" are worked out here from the data,
    and the other two say "review" (a person must look).
  * Student reports = open `question_reports`, counted per reason.
  * A decision (approve / reject) is saved as an admin `question_reviews` row; the time from the
    question's creation to that row is the "average review time".

Rules:
  * SQL lives in `repository.py`, not here.
  * To use another module, call ITS service (e.g. `from api.modules.syllabus import service`),
    never its repository.
"""

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from api.core import clock
from api.modules.quality import repository
from api.modules.quality.schemas import (
    CheckName,
    CheckResult,
    ModuleStatus,
    QualityCheckOut,
    QualityItemOut,
    QualityQueueOut,
    StudentReportOut,
)
from api.modules.questions import service as questions_service
from shared.db.models import Question, QuestionReview

MODULE_NAME = "quality"
REVIEW_TIME_DAYS = 30

# Keys the AI reviewer may use in question_reviews.checks, for each check on screen.
CHECK_KEYS: dict[CheckName, tuple[str, ...]] = {
    "Single correct answer": ("single_correct_answer", "one_correct_answer"),
    "Distractor quality": ("distractor_quality", "distractors"),
    "Syllabus match": ("syllabus_match", "in_syllabus"),
    "Duplicate check": ("duplicate_check", "not_duplicate"),
}
REASON_TEXT = {
    "wrong_answer": "Wrong answer key",
    "unclear": "Question is unclear",
    "typo": "Typo",
    "out_of_syllabus": "Not in the syllabus",
    "duplicate": "Duplicate question",
    "other": "Other",
}
NOT_CHECKED = "Not checked by the AI reviewer yet."


async def get_status() -> ModuleStatus:
    """Placeholder used by the status route."""
    return ModuleStatus(module=MODULE_NAME, status="todo")


# --------------------------------------------------------------------------- checks (pure)


def check_from_ai(name: CheckName, value: Any) -> QualityCheckOut | None:
    """One stored AI result -> a check. Accepts true/false, "pass"/"review"/"fail", or
    {"result": ..., "note": ...}. Anything else = None (not usable)."""
    note = ""
    if isinstance(value, dict):
        note = str(value.get("note") or "")
        value = value.get("result", value.get("passed"))
    if isinstance(value, bool):
        result: CheckResult = "pass" if value else "fail"
    elif value in ("pass", "review", "fail"):
        result = value
    else:
        return None
    default = {"pass": "No issues found.", "review": "Needs a closer look.", "fail": "Failed."}
    return QualityCheckOut(name=name, result=result, note=note or default[result])


def rule_checks(
    question: Question, options: tuple[int, int] | None, duplicate_of: int | None
) -> dict[CheckName, QualityCheckOut]:
    """The checks we can work out without the AI."""
    checks: dict[CheckName, QualityCheckOut] = {}
    if question.question_type.value == "mcq":
        total, correct = options or (0, 0)
        checks["Single correct answer"] = (
            QualityCheckOut(name="Single correct answer", result="pass", note="One correct option.")
            if correct == 1
            else QualityCheckOut(
                name="Single correct answer",
                result="fail",
                note=f"{correct} of {total} options are marked correct.",
            )
        )
    else:
        checks["Single correct answer"] = QualityCheckOut(
            name="Single correct answer", result="pass", note="Not an MCQ."
        )
    checks["Duplicate check"] = (
        QualityCheckOut(
            name="Duplicate check", result="fail", note=f"Same text as Q-{duplicate_of}."
        )
        if duplicate_of is not None
        else QualityCheckOut(
            name="Duplicate check", result="pass", note="No other question has the same text."
        )
    )
    return checks


def build_checks(
    question: Question,
    ai_checks: dict[str, Any],
    options: tuple[int, int] | None,
    duplicate_of: int | None,
) -> list[QualityCheckOut]:
    """The four checks in screen order: the AI's result when it has one, else our rules."""
    rules = rule_checks(question, options, duplicate_of)
    out = []
    for name, keys in CHECK_KEYS.items():
        found = next((check_from_ai(name, ai_checks[k]) for k in keys if k in ai_checks), None)
        out.append(
            found
            or rules.get(name)
            or QualityCheckOut(name=name, result="review", note=NOT_CHECKED)
        )
    return out


# --------------------------------------------------------------------------- queue + decisions


async def review_queue(session: AsyncSession) -> QualityQueueOut:
    rows = await repository.review_queue(session)
    questions = [q for q, _, _ in rows]
    ids = [q.id for q in questions]
    ai_checks = await repository.latest_ai_checks(session, ids)
    options = await questions_service.option_counts(session, ids)
    duplicates = await repository.same_stem_numbers(session, questions)
    reports = await repository.open_report_counts(session, ids)
    minutes = await repository.average_review_minutes(
        session, clock.now() - timedelta(days=REVIEW_TIME_DAYS)
    )

    items = [
        QualityItemOut(
            id=q.id,
            code=questions_service.question_code(q),
            stem=q.stem,
            unit_number=unit.number if unit else None,
            topic_code=(topic.code or topic.number) if topic else None,
            checks=build_checks(
                q, ai_checks.get(q.id, {}), options.get(q.id), duplicates.get(q.id)
            ),
            student_reports=[
                StudentReportOut(text=REASON_TEXT.get(reason, reason.replace("_", " ")), count=n)
                for reason, n in reports.get(q.id, [])
            ],
        )
        for q, topic, unit in rows
    ]
    return QualityQueueOut(
        in_queue=len(items),
        auto_check_failed=sum(1 for i in items if any(c.result == "fail" for c in i.checks)),
        with_student_reports=sum(1 for i in items if i.student_reports),
        avg_review_minutes=round(minutes) if minutes is not None else None,
        items=items,
    )


async def record_decision(
    session: AsyncSession, admin_id: uuid.UUID, question_id: uuid.UUID, approve: bool
) -> None:
    """Approve (same rules as publishing) or reject, and save the decision with its time.

    404 QUESTION_NOT_FOUND · 422 QUESTION_INCOMPLETE."""
    question = await questions_service.admin_set_review_status(session, question_id, approve)
    await repository.add_review(
        session,
        QuestionReview(
            question_id=question.id,
            reviewer_id=admin_id,
            reviewer_type="admin",
            verdict="approve" if approve else "reject",
            checks={},
        ),
    )
    await session.commit()


async def pending_counts(session: AsyncSession, older_than: Any) -> tuple[int, int]:
    """For the admin dashboard: (waiting, waiting longer than `older_than`)."""
    return await repository.pending_counts(session, older_than)


async def ai_questions_per_day(session: AsyncSession, since: Any) -> dict[Any, int]:
    return await repository.ai_questions_per_day(session, since)
