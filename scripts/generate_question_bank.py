"""Generate practice questions from the approved books, for an admin to review.

    python scripts/generate_question_bank.py                        # 3 MCQs per topic + written
    python scripts/generate_question_bank.py --mcq-per-topic 5
    python scripts/generate_question_bank.py --units 4 10           # only these units

Run scripts/seed_customer.py --only knowledge-base first: without books nothing is generated.

* New questions are saved as PENDING REVIEW, so students don't see them yet. Open
  Admin > Quality review, check them and approve. Approving a written question also approves
  its marking scheme.
* A question that fails an automatic check (wrong shape, blind reviewer disagrees with the
  answer key, duplicate) is thrown away.
* Topics are visited unit by unit in turn, so every unit gets questions early.
* Safe to re-run: each topic is only topped up to the target. When the free AI requests run
  out it stops cleanly: run the same command again later to continue.
* If Gemini is overloaded it waits and tries again, then stops instead of wasting requests.
  Ctrl+C is safe too: finished questions stay saved.
"""

import argparse
import asyncio
import logging
import sys
import uuid
from dataclasses import dataclass
from itertools import zip_longest
from typing import Any

import _bootstrap  # noqa: F401
from sqlalchemy import func, select

from ai_service.daily_limits import DailyLimitReached
from ai_service.pipelines.questions import mcq_mapping
from ai_service.pipelines.questions.generate_questions import (
    DIFFICULTY_PROMPT_ID,
    NoContextError,
    generate_for_topic,
)
from ai_service.pipelines.questions.generate_written import PROMPT_ID as WRITTEN_PROMPT_ID
from ai_service.pipelines.questions.generate_written import generate_written
from ai_service.pipelines.questions.quality_checks import (
    blind_check,
    review_questions,
    review_written,
)
from api.modules.knowledge_base import service as knowledge_service
from shared.db.models import MCQOption, Misconception, Question, QuestionReview, Topic, Unit
from shared.db.session import SessionLocal
from shared.enums import ContentStatus, Difficulty, QuestionType

LETTERS = "ABCDE"
DIFFICULTIES = ("easy", "medium", "hard")
# Rejected and archived questions don't count towards a topic's target.
ACTIVE = (ContentStatus.DRAFT, ContentStatus.PENDING_REVIEW, ContentStatus.APPROVED)
BUSY_ROUNDS = 3  # tries per topic while Gemini is overloaded, then the run stops
BUSY_WAIT_SECONDS = 60
REVIEWER_WAIT_SECONDS = 30


class GeminiStillBusy(Exception):
    """Gemini stayed overloaded, so stop instead of using up the daily requests."""


@dataclass(frozen=True)
class TopicInfo:
    """Plain copies of the values we need: database rows expire after every commit."""

    id: uuid.UUID
    title: str
    order_index: int
    unit_id: uuid.UUID
    unit_number: int


def checks_for_review(kind: QuestionType, answer_confirmed: bool = True) -> dict[str, Any]:
    """What the Quality review screen shows. An MCQ whose answer could not be double-checked
    is marked "review", so "Approve all passing" leaves it for a person."""
    is_mcq = kind == QuestionType.MCQ
    if is_mcq and not answer_confirmed:
        answer_check = {
            "result": "review",
            "note": "The AI reviewer was busy. Please check the answer key yourself.",
        }
    else:
        answer_check = {
            "result": "pass",
            "note": "A blind AI reviewer chose the same answer." if is_mcq else "Not an MCQ.",
        }
    return {
        "single_correct_answer": answer_check,
        "distractor_quality": {
            "result": "pass",
            "note": "Five different options." if is_mcq else "Not an MCQ.",
        },
        "syllabus_match": {"result": "pass", "note": "Written from the approved books."},
        "duplicate_check": {"result": "pass", "note": "Not a duplicate."},
    }


def topics_in_turn(rows: list[TopicInfo]) -> list[TopicInfo]:
    """First topic of every unit, then the second of every unit, and so on."""
    by_unit: dict[int, list[TopicInfo]] = {}
    for topic in rows:
        by_unit.setdefault(topic.unit_number, []).append(topic)
    columns = [by_unit[number] for number in sorted(by_unit)]
    return [row for group in zip_longest(*columns) for row in group if row is not None]


async def count_questions(session: Any, topic_id: uuid.UUID, kind: QuestionType) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(Question)
        .where(
            Question.topic_id == topic_id,
            Question.question_type == kind,
            Question.status.in_(ACTIVE),
        )
    )
    return int(result.scalar_one())


async def existing_stems(session: Any, topic_id: uuid.UUID) -> list[str]:
    result = await session.execute(select(Question.stem).where(Question.topic_id == topic_id))
    return [str(stem) for stem in result.scalars()]


async def add_question(
    session: Any,
    topic: TopicInfo,
    kind: QuestionType,
    difficulty: str,
    stem: str,
    marks: int,
    explanation: str | None,
    prompt_version: str,
    answer_confirmed: bool = True,
) -> Question:
    question = Question(
        id=uuid.uuid4(),
        topic_id=topic.id,
        unit_id=topic.unit_id,
        question_type=kind,
        difficulty=Difficulty(difficulty),
        stem=stem,
        explanation=explanation,
        marks=marks,
        source="ai",
        status=ContentStatus.PENDING_REVIEW,
        prompt_version=prompt_version,
    )
    session.add(question)
    await session.flush()  # the review row points at this question, so save it first
    session.add(
        QuestionReview(
            question_id=question.id,
            reviewer_type="ai",
            verdict="accept",
            checks=checks_for_review(kind, answer_confirmed),
        )
    )
    return question


async def misconception_titles(item: dict[str, Any]) -> dict[str, str] | None:
    """{option label: the wrong idea behind it}, or None if a wrong option has no title."""
    options = [
        {"label": label, "text": text, "is_correct": text == item["correct_answer"]}
        for label, text in zip(LETTERS, item["options"], strict=False)
    ]
    result = await mcq_mapping.run(
        {"question": {"question": item["question"], "options": options}, "misconceptions": []}
    )
    titles = {
        str(m["option_label"]): " ".join(str(m["new_misconception_title"]).split())[:200]
        for m in result["mappings"]
        if m.get("new_misconception_title")
    }
    wrong = [o["label"] for o in options if not o["is_correct"]]
    return titles if all(titles.get(label) for label in wrong) else None


async def misconception_id(session: Any, title: str) -> uuid.UUID:
    """The misconception with this title (reused if it already exists)."""
    result = await session.execute(
        select(Misconception.id).where(
            Misconception.concept_id.is_(None), Misconception.title == title
        )
    )
    existing = result.scalars().first()
    if existing is not None:
        return uuid.UUID(str(existing))
    row = Misconception(id=uuid.uuid4(), title=title)
    session.add(row)
    await session.flush()
    return row.id


async def confirm_answer(item: dict[str, Any], review: dict[str, Any]) -> bool | None:
    """True = a blind reviewer agreed, False = it could not check, None = it disagreed."""
    blind = review.get("checks", {}).get("blind_review", {})
    if blind.get("skipped") == "reviewer unavailable":
        await asyncio.sleep(REVIEWER_WAIT_SECONDS)
        blind = await blind_check(item)
    if blind.get("passed") is False:
        return None
    return blind.get("passed") is True


async def top_up_mcqs(session: Any, topic: TopicInfo, target: int) -> int:
    missing = target - await count_questions(session, topic.id, QuestionType.MCQ)
    if missing <= 0:
        return 0
    difficulty = DIFFICULTIES[topic.order_index % len(DIFFICULTIES)]
    generated, _ = await generate_for_topic(
        topic.title, missing, unit_id=topic.unit_id, difficulty=difficulty
    )
    items = [q.model_dump() for q in generated]
    reviews = await review_questions(items, await existing_stems(session, topic.id))
    saved = 0
    for item, review in zip(items, reviews, strict=True):
        if not review["passed"]:
            continue
        confirmed = await confirm_answer(item, review)
        if confirmed is None:
            continue  # the second look chose a different answer: don't keep it
        # An MCQ can only be published when every wrong option names its misconception.
        titles = await misconception_titles(item)
        if titles is None:
            continue
        question = await add_question(
            session,
            topic,
            QuestionType.MCQ,
            difficulty,
            item["question"],
            1,
            item.get("explanation") or None,
            DIFFICULTY_PROMPT_ID,
            confirmed,
        )
        for label, text in zip(LETTERS, item["options"], strict=False):
            is_correct = text == item["correct_answer"]
            misconception = None if is_correct else await misconception_id(session, titles[label])
            session.add(
                MCQOption(
                    question_id=question.id,
                    label=label,
                    text=text,
                    is_correct=is_correct,
                    misconception_id=misconception,
                )
            )
        await session.commit()  # saved one by one, so a stop keeps the finished questions
        saved += 1
    return saved


async def top_up_written(session: Any, topic: TopicInfo, kind: QuestionType, target: int) -> int:
    missing = target - await count_questions(session, topic.id, kind)
    if missing <= 0:
        return 0
    generated, _ = await generate_written(
        topic.title, missing, question_type=kind.value, unit_id=topic.unit_id
    )
    items = [{**q.model_dump(), "question_type": kind.value} for q in generated]
    reviews = await review_written(items, await existing_stems(session, topic.id))
    saved = 0
    for item, review in zip(items, reviews, strict=True):
        if not review["passed"]:
            continue
        question = await add_question(
            session,
            topic,
            kind,
            "medium",
            item["question"],
            int(item["marks"]),
            None,
            WRITTEN_PROMPT_ID,
        )
        await knowledge_service.save_ai_marking_scheme(
            session, question.id, item["model_answer"], item["points"]
        )
        saved += 1
    await session.commit()
    return saved


def is_gemini_busy(error: Exception) -> bool:
    return isinstance(error, RuntimeError) and "Gemini failed after retries" in str(error)


async def process_topic(
    session: Any, topic: TopicInfo, args: argparse.Namespace
) -> tuple[int, int]:
    """Top up one topic. Returns (new MCQs, new written questions)."""
    mcq = await top_up_mcqs(session, topic, args.mcq_per_topic)
    structured = await top_up_written(
        session, topic, QuestionType.STRUCTURED, args.structured_per_topic
    )
    essay = await top_up_written(session, topic, QuestionType.ESSAY, args.essay_per_topic)
    return mcq, structured + essay


async def process_with_waits(
    session: Any, topic: TopicInfo, args: argparse.Namespace
) -> tuple[int, int]:
    """Gemini overloaded -> wait and try this topic again; still busy -> GeminiStillBusy."""
    for round_number in range(1, BUSY_ROUNDS + 1):
        try:
            return await process_topic(session, topic, args)
        except RuntimeError as exc:
            if not is_gemini_busy(exc):
                raise
            await session.rollback()
            if round_number == BUSY_ROUNDS:
                raise GeminiStillBusy from exc
            print(f"    Gemini is busy. Waiting {BUSY_WAIT_SECONDS} seconds...", flush=True)
            await asyncio.sleep(BUSY_WAIT_SECONDS)
    raise GeminiStillBusy


async def count_generated(session: Any) -> dict[str, int]:
    result = await session.execute(
        select(Question.question_type, func.count())
        .where(Question.source == "ai", Question.status.in_(ACTIVE))
        .group_by(Question.question_type)
    )
    return {str(kind.value): int(n) for kind, n in result.all()}


async def run(args: argparse.Namespace) -> int:
    async with SessionLocal() as session:
        stmt = (
            select(Topic, Unit)
            .join(Unit, Topic.unit_id == Unit.id)
            .order_by(Unit.number, Topic.order_index)
        )
        if args.units:
            stmt = stmt.where(Unit.number.in_(args.units))
        rows = [
            TopicInfo(t.id, t.title, t.order_index or 0, u.id, u.number)
            for t, u in (await session.execute(stmt)).all()
        ]
        if not rows:
            print("No topics found. Run scripts/seed_customer.py first.")
            return 1

        before = await count_generated(session)
        failed: list[str] = []
        try:
            for number, topic in enumerate(topics_in_turn(rows), 1):
                label = f"Unit {topic.unit_number} · {topic.title}"
                print(f"[{number}/{len(rows)}] {label}: working...", flush=True)
                try:
                    mcq, written = await process_with_waits(session, topic, args)
                except (DailyLimitReached, GeminiStillBusy):
                    raise
                except NoContextError:
                    await session.rollback()
                    failed.append(f"{label}: no book text found")
                    print("    no book text found", flush=True)
                    continue
                except Exception as exc:
                    await session.rollback()
                    failed.append(f"{label}: {type(exc).__name__}")
                    print(f"    failed ({type(exc).__name__})", flush=True)
                    continue
                print(f"    done: +{mcq} MCQ, +{written} written", flush=True)
        except DailyLimitReached:
            await session.rollback()
            print("\nGemini's free limit is reached for now. Run this command again later.")
        except GeminiStillBusy:
            await session.rollback()
            print("\nGemini is overloaded right now. Run this command again in 30-60 minutes.")

        after = await count_generated(session)

    added = {
        kind: after.get(kind, 0) - before.get(kind, 0) for kind in ("mcq", "structured", "essay")
    }
    print(f"\nAdded {added['mcq']} MCQs, {added['structured']} structured, {added['essay']} essay")
    print("Next: Admin > Quality review > check them and approve.")
    if failed:
        print(f"{len(failed)} topic(s) had a problem; run again to retry them:")
        for line in failed:
            print(f"  {line}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mcq-per-topic", type=int, default=3)
    parser.add_argument("--structured-per-topic", type=int, default=1)
    parser.add_argument("--essay-per-topic", type=int, default=1)
    parser.add_argument("--units", type=int, nargs="*", help="Only these unit numbers")
    # Our own short messages replace the long retry logs.
    logging.getLogger("ai_service.providers.llm_gemini").setLevel(logging.ERROR)
    logging.getLogger("ai_service.pipelines.questions.quality_checks").setLevel(logging.ERROR)
    print("Gemini can take a few minutes when it is busy. Ctrl+C is safe.", flush=True)
    try:
        return asyncio.run(run(parser.parse_args()))
    except KeyboardInterrupt:
        print("\nStopped. Finished questions are saved. Run the same command to continue.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
