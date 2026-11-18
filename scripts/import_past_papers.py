"""Import one past paper from JSON into papers / questions / mcq_options / paper_questions.

Owner: Udith. The JSON format is documented in data/questions/README.md.

    python scripts/import_past_papers.py --file data/questions/2023_part_1.json
    python scripts/import_past_papers.py --file data/questions/2023_part_1.json --dry-run

* The whole file is checked first (and every "topic" is matched to a seeded topic title, exact,
  else "contains", case-insensitive). If anything is wrong NOTHING is written and every problem
  is listed, so run scripts/seed_syllabus.py first.
* Creates one `papers` row (paper_type="past_paper") and one approved question per item
  (source="past_paper", year, paper_part, question_number), linked in file order.
* Safe to re-run: a question that already exists for the same year + part + number is reused
  (not changed), and the paper with the same year + title is reused; only missing links are
  added (at the end).
"""

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Works as `python scripts/import_past_papers.py` AND `python -m scripts.import_past_papers`
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from shared.db.models import MCQOption, Paper, PaperQuestion, Question, Topic  # noqa: E402
from shared.db.session import SessionLocal  # noqa: E402
from shared.enums import (  # noqa: E402
    ContentStatus,
    Difficulty,
    PaperKind,
    PaperPart,
    QuestionType,
)

LETTERS = "ABCDE"
# A/L Biology: Paper I is MCQ, Paper II part A is structured, part B is essay.
TYPE_OF_PART = {
    PaperPart.PART_1: QuestionType.MCQ,
    PaperPart.PART_2A: QuestionType.STRUCTURED,
    PaperPart.PART_2B: QuestionType.ESSAY,
}
PART_NAMES = {
    PaperPart.PART_1: "Paper I (MCQ)",
    PaperPart.PART_2A: "Paper II Part A (structured)",
    PaperPart.PART_2B: "Paper II Part B (essay)",
}


class PaperFileError(ValueError):
    """The JSON file is not valid. `problems` lists every problem found."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = problems


@dataclass
class ParsedQuestion:
    number: str
    topic: str
    stem: str
    marks: int
    question_type: QuestionType
    options: list[str] = field(default_factory=list)
    correct_answer: str | None = None
    explanation: str | None = None
    difficulty: Difficulty = Difficulty.MEDIUM


@dataclass
class ParsedPaper:
    year: int
    paper_part: PaperPart
    title: str
    duration_minutes: int | None
    questions: list[ParsedQuestion]


@dataclass
class ImportReport:
    paper_id: Any = None
    paper_created: bool = False
    created: int = 0
    reused: int = 0
    linked: int = 0


def _text(value: Any) -> str:
    return " ".join(str(value).split()) if isinstance(value, str) else ""


def parse_paper(data: Any) -> ParsedPaper:
    """Check the JSON (see data/questions/README.md). Raises PaperFileError with all problems."""
    problems: list[str] = []
    if not isinstance(data, dict):
        raise PaperFileError(["The file must be one JSON object (a paper), not a list"])

    year = data.get("year")
    if not isinstance(year, int) or isinstance(year, bool) or not 1990 <= year <= 2100:
        problems.append("year: a whole number between 1990 and 2100 is needed")
        year = 0
    try:
        part = PaperPart(data.get("paper_part"))
    except ValueError:
        problems.append(f"paper_part: one of {', '.join(p.value for p in PaperPart)}")
        part = PaperPart.PART_1
    duration = data.get("duration_minutes")
    if duration is not None and (not isinstance(duration, int) or duration <= 0):
        problems.append("duration_minutes: a positive whole number (or leave it out)")
        duration = None
    title = _text(data.get("title")) or f"{year} A/L Biology {PART_NAMES[part]}"

    items = data.get("questions")
    if not isinstance(items, list) or not items:
        problems.append("questions: a non-empty list is needed")
        items = []

    question_type = TYPE_OF_PART[part]
    questions: list[ParsedQuestion] = []
    seen: set[str] = set()
    for i, item in enumerate(items, start=1):
        where = f"questions[{i}]"
        if not isinstance(item, dict):
            problems.append(f"{where}: must be an object")
            continue
        number = _text(str(item.get("number", "")) if item.get("number") is not None else "")
        where = f"questions[{i}] (number {number or '?'})"
        if not number or len(number) > 10:
            problems.append(f'{where}: number is needed, max 10 characters (e.g. "23", "5(b)")')
        elif number in seen:
            problems.append(f"{where}: number {number} appears twice")
        seen.add(number)
        topic = _text(item.get("topic"))
        if not topic:
            problems.append(f"{where}: topic is needed (a seeded topic title)")
        stem = str(item.get("question") or "").strip()
        if not stem:
            problems.append(f"{where}: question (the text) is needed")
        default_marks = 1 if question_type == QuestionType.MCQ else None
        marks = item.get("marks", default_marks)
        if not isinstance(marks, int) or isinstance(marks, bool) or marks <= 0:
            problems.append(f"{where}: marks must be a positive whole number")
            marks = 1
        try:
            difficulty = Difficulty(item.get("difficulty") or Difficulty.MEDIUM)
        except ValueError:
            problems.append(f"{where}: difficulty is easy, medium or hard")
            difficulty = Difficulty.MEDIUM

        options: list[str] = []
        correct: str | None = None
        if question_type == QuestionType.MCQ:
            raw = item.get("options")
            options = [_text(o) for o in raw] if isinstance(raw, list) else []
            if not 4 <= len(options) <= len(LETTERS) or not all(options):
                problems.append(f"{where}: options must be 4 or 5 non-empty texts")
            elif len({o.lower() for o in options}) != len(options):
                problems.append(f"{where}: two options have the same text")
            correct = _text(item.get("correct_answer"))
            if correct not in options:
                problems.append(f"{where}: correct_answer must be exactly one of the options")
        elif "options" in item:
            problems.append(f"{where}: only {PART_NAMES[PaperPart.PART_1]} questions have options")

        explanation = str(item.get("explanation") or "").strip() or None
        questions.append(
            ParsedQuestion(
                number=number,
                topic=topic,
                stem=stem,
                marks=marks,
                question_type=question_type,
                options=options,
                correct_answer=correct,
                explanation=explanation,
                difficulty=difficulty,
            )
        )
    if problems:
        raise PaperFileError(problems)
    return ParsedPaper(
        year=year, paper_part=part, title=title, duration_minutes=duration, questions=questions
    )


def match_topic(name: str, topics: dict[str, Topic]) -> Topic | None:
    """Same rule as scripts/import_question_bank.py: exact title, else one "contains" match."""
    key = name.strip().lower()
    if key in topics:
        return topics[key]
    matches = [t for title, t in topics.items() if key in title or title in key]
    return matches[0] if len(matches) == 1 else None


async def import_paper(session: AsyncSession, paper: ParsedPaper) -> ImportReport:
    """Write the paper (no commit). Raises PaperFileError when a topic doesn't match."""
    topics = {t.title.lower(): t for t in (await session.execute(select(Topic))).scalars()}
    by_question: dict[str, Topic] = {}
    unmatched = []
    for q in paper.questions:
        topic = match_topic(q.topic, topics)
        if topic is None:
            unmatched.append(f"question {q.number}: no seeded topic matches '{q.topic}'")
        else:
            by_question[q.number] = topic
    if unmatched:
        raise PaperFileError(unmatched)

    report = ImportReport()
    existing = {
        q.question_number: q
        for q in (
            await session.execute(
                select(Question).where(
                    Question.source == "past_paper",
                    Question.year == paper.year,
                    Question.paper_part == paper.paper_part,
                )
            )
        ).scalars()
    }
    questions: list[Question] = []
    for q in paper.questions:
        found = existing.get(q.number)
        if found is not None:
            report.reused += 1
            questions.append(found)
            continue
        topic = by_question[q.number]
        row = Question(
            topic_id=topic.id,
            unit_id=topic.unit_id,
            question_type=q.question_type,
            difficulty=q.difficulty,
            stem=q.stem,
            explanation=q.explanation,
            marks=q.marks,
            source="past_paper",
            year=paper.year,
            paper_part=paper.paper_part,
            question_number=q.number,
            status=ContentStatus.APPROVED,
        )
        session.add(row)
        await session.flush()
        for label, text in zip(LETTERS, q.options, strict=False):
            session.add(
                MCQOption(
                    question_id=row.id, label=label, text=text, is_correct=text == q.correct_answer
                )
            )
        report.created += 1
        questions.append(row)

    row_paper = (
        await session.execute(
            select(Paper).where(
                Paper.paper_type == PaperKind.PAST_PAPER.value,
                Paper.year == paper.year,
                Paper.title == paper.title,
            )
        )
    ).scalar_one_or_none()
    if row_paper is None:
        row_paper = Paper(
            title=paper.title,
            paper_type=PaperKind.PAST_PAPER.value,
            year=paper.year,
            duration_minutes=paper.duration_minutes,
            status=ContentStatus.APPROVED,
            blueprint={"paper_part": paper.paper_part.value, "source": "import"},
        )
        session.add(row_paper)
        await session.flush()
        report.paper_created = True
    row_paper.unit_ids = sorted({t.unit_id for t in by_question.values()}, key=str)
    row_paper.total_marks = sum(q.marks for q in questions)
    report.paper_id = row_paper.id

    linked = set(
        (
            await session.execute(
                select(PaperQuestion.question_id).where(PaperQuestion.paper_id == row_paper.id)
            )
        ).scalars()
    )
    position = (
        await session.scalar(
            select(func.coalesce(func.max(PaperQuestion.position), 0)).where(
                PaperQuestion.paper_id == row_paper.id
            )
        )
        or 0
    )
    for question in questions:
        if question.id in linked:
            continue
        position += 1
        session.add(
            PaperQuestion(
                paper_id=row_paper.id,
                question_id=question.id,
                position=position,
                marks=question.marks,
            )
        )
        report.linked += 1
    await session.flush()
    return report


async def run(path: Path, dry_run: bool = False) -> int:
    try:
        paper = parse_paper(json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as exc:
        print(f"{path}: not valid JSON ({exc})")
        return 1
    except PaperFileError as exc:
        print(f"{path}: {len(exc.problems)} problem(s), nothing imported:")
        for problem in exc.problems:
            print(f"  - {problem}")
        return 1
    async with SessionLocal() as session:
        try:
            report = await import_paper(session, paper)
        except PaperFileError as exc:
            await session.rollback()
            print(f"{path}: nothing imported:")
            for problem in exc.problems:
                print(f"  - {problem}")
            print("Rename the topics to seeded topic titles (scripts/seed_syllabus.py).")
            return 1
        if dry_run:
            await session.rollback()
        else:
            await session.commit()
    verb = "Would import" if dry_run else "Imported"
    paper_note = "new paper" if report.paper_created else "existing paper"
    print(
        f"{verb} '{paper.title}' ({paper_note}): {report.created} new questions, "
        f"{report.reused} already there, {report.linked} linked to the paper."
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Import one past paper (JSON) into the database")
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true", help="check everything, write nothing")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.file, args.dry_run)))


if __name__ == "__main__":
    main()
