"""Import MCQs from data/questions/question_bank.json into questions + mcq_options. Owner: Udith.

The JSON format is Udith's original question bank:
    {"id", "topic", "unit", "question", "options": [4-5 strings], "correct_answer", "marks", "year"}

* "topic" is matched to a seeded topic title (exact, else "contains", case-insensitive),
  so run scripts/seed_syllabus.py first.
* Imported questions are approved (they were written by the team) and are used as style
  examples when the AI generates papers.
* Safe to re-run: a question with the same text in the same topic is skipped.

    python scripts/import_question_bank.py
    python scripts/import_question_bank.py --file data/questions/other.json
"""

import argparse
import asyncio
import json
from pathlib import Path

import _bootstrap  # noqa: F401
from sqlalchemy import select

from shared.db.models import MCQOption, Question, Topic
from shared.db.session import SessionLocal
from shared.enums import ContentStatus, QuestionType

DEFAULT_FILE = _bootstrap.REPO_ROOT / "data" / "questions" / "question_bank.json"
LETTERS = "ABCDE"


def match_topic(name: str, topics: dict[str, Topic]) -> Topic | None:
    key = name.strip().lower()
    if key in topics:
        return topics[key]
    matches = [t for title, t in topics.items() if key in title or title in key]
    return matches[0] if len(matches) == 1 else None


async def run(path: Path) -> int:
    items = json.loads(path.read_text(encoding="utf-8"))
    imported = skipped = 0
    unmatched: set[str] = set()
    async with SessionLocal() as session:
        topics = {t.title.lower(): t for t in (await session.execute(select(Topic))).scalars()}
        if not topics:
            raise SystemExit("No topics in the database. Run scripts/seed_syllabus.py first.")

        for item in items:
            if item["correct_answer"] not in item["options"]:
                print(f"  SKIP {item.get('id')}: correct_answer is not one of the options")
                continue
            topic = match_topic(item["topic"], topics)
            if topic is None:
                unmatched.add(item["topic"])
                continue
            exists = await session.execute(
                select(Question.id).where(
                    Question.topic_id == topic.id, Question.stem == item["question"]
                )
            )
            if exists.first():
                skipped += 1
                continue

            question = Question(
                topic_id=topic.id,
                question_type=QuestionType.MCQ,
                stem=item["question"],
                marks=int(item.get("marks", 1)),
                year=item.get("year"),
                source="past_paper" if item.get("year") else "manual",
                status=ContentStatus.APPROVED,
            )
            session.add(question)
            await session.flush()
            for label, text in zip(LETTERS, item["options"], strict=False):
                session.add(
                    MCQOption(
                        question_id=question.id,
                        label=label,
                        text=text,
                        is_correct=text == item["correct_answer"],
                    )
                )
            imported += 1
        await session.commit()

    print(f"Imported {imported}, already there {skipped}.")
    if unmatched:
        print(f"No matching topic for: {sorted(unmatched)} (rename them to a seeded topic title)")
    return 1 if unmatched else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Import the MCQ question bank")
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE)
    raise SystemExit(asyncio.run(run(parser.parse_args().file)))


if __name__ == "__main__":
    main()
