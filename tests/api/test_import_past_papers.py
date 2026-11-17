"""scripts/import_past_papers.py: the JSON format (data/questions/README.md) and the import."""

import json
import random
import uuid
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from scripts.import_past_papers import PaperFileError, import_paper, parse_paper
from shared.db.models import MCQOption, Paper, PaperQuestion, Question, Topic, Unit
from shared.enums import ContentStatus, PaperPart, QuestionType

EXAMPLE = Path(__file__).resolve().parents[2] / "data" / "questions" / "example_past_paper.json"


def mcq(number: str, **extra) -> dict:  # type: ignore[no-untyped-def]
    return {
        "number": number,
        "topic": "Import topic",
        "question": f"Question {number}?",
        "options": ["A1", "B1", "C1", "D1"],
        "correct_answer": "B1",
        **extra,
    }


def paper(**extra) -> dict:  # type: ignore[no-untyped-def]
    return {"year": 2020, "paper_part": "part_1", "questions": [mcq("1"), mcq("2")], **extra}


def test_example_file_is_valid():
    parsed = parse_paper(json.loads(EXAMPLE.read_text(encoding="utf-8")))
    assert parsed.paper_part == PaperPart.PART_1 and len(parsed.questions) == 2
    assert parsed.questions[1].marks == 1  # MCQ default


def test_defaults_and_cleaning():
    parsed = parse_paper(paper(questions=[mcq(" 5 ", options=[" A1 ", "B1", "C1", "D1"])]))
    assert parsed.title == "2020 A/L Biology Paper I (MCQ)"
    [q] = parsed.questions
    assert (q.number, q.options[0], q.question_type) == ("5", "A1", QuestionType.MCQ)


def test_every_problem_is_listed():
    with pytest.raises(PaperFileError) as err:
        parse_paper(
            {
                "year": 1800,
                "paper_part": "part_9",
                "questions": [
                    mcq("1", correct_answer="Z"),
                    mcq("1"),
                    mcq("3", options=["a", "b"]),
                    {"number": "4", "question": "", "options": ["a", "b", "c", "d"]},
                ],
            }
        )
    text = "\n".join(err.value.problems)
    for expected in ["year", "paper_part", "correct_answer", "appears twice", "4 or 5",
                     "topic is needed", "question (the text)"]:  # fmt: skip
        assert expected in text, expected


def test_paper_two_needs_marks_and_has_no_options():
    with pytest.raises(PaperFileError) as err:
        parse_paper(
            {
                "year": 2020,
                "paper_part": "part_2a",
                "questions": [
                    {"number": "1(a)", "topic": "t", "question": "Explain osmosis."},
                    {"number": "1(b)", "topic": "t", "question": "x", "marks": 4, "options": []},
                ],
            }
        )
    assert any("marks" in p for p in err.value.problems)
    assert any("only Paper I" in p for p in err.value.problems)
    ok = parse_paper({"year": 2020, "paper_part": "part_2b",
                      "questions": [{"number": "7", "topic": "t", "question": "Essay", "marks": 15}]})  # fmt: skip
    assert ok.questions[0].question_type == QuestionType.ESSAY


def test_not_an_object():
    with pytest.raises(PaperFileError):
        parse_paper([mcq("1")])


# --------------------------------------------------------------------------- database


@pytest.fixture
async def topic(db_session):  # type: ignore[no-untyped-def]
    unit = Unit(number=random.randint(100_000, 899_000), title="Import unit")
    db_session.add(unit)
    await db_session.flush()
    row = Topic(unit_id=unit.id, number="I.1", title=f"Import topic {uuid.uuid4().hex[:6]}")
    db_session.add(row)
    await db_session.commit()
    year = random.randint(1990, 2100)
    yield row, year
    await db_session.rollback()
    await db_session.execute(
        delete(Paper).where(Paper.paper_type == "past_paper", Paper.title.like("Import test%"))
    )
    await db_session.execute(delete(Question).where(Question.topic_id == row.id))
    await db_session.execute(delete(Topic).where(Topic.id == row.id))
    await db_session.execute(delete(Unit).where(Unit.id == unit.id))
    await db_session.commit()


@pytest.mark.db
async def test_import_creates_paper_questions_and_links(db_session, topic):
    row, year = topic
    data = paper(year=year, title=f"Import test {year}",
                 questions=[mcq("1", topic=row.title), mcq("2", topic=row.title, marks=2)])  # fmt: skip
    first = await import_paper(db_session, parse_paper(data))
    await db_session.commit()
    assert (first.paper_created, first.created, first.reused, first.linked) == (True, 2, 0, 2)

    saved = await db_session.get(Paper, first.paper_id)
    assert (saved.total_marks, saved.status, saved.unit_ids) == (3, ContentStatus.APPROVED,
                                                                 [row.unit_id])  # fmt: skip
    links = (
        await db_session.execute(
            select(Question.question_number, PaperQuestion.position)
            .join(PaperQuestion, PaperQuestion.question_id == Question.id)
            .where(PaperQuestion.paper_id == saved.id)
            .order_by(PaperQuestion.position)
        )
    ).all()
    assert [tuple(r) for r in links] == [("1", 1), ("2", 2)]
    q1 = (
        await db_session.execute(
            select(Question).where(Question.topic_id == row.id, Question.question_number == "1")
        )
    ).scalar_one()
    assert (q1.source, q1.year, q1.paper_part) == ("past_paper", year, PaperPart.PART_1)
    correct = (
        await db_session.execute(
            select(MCQOption.label).where(MCQOption.question_id == q1.id, MCQOption.is_correct)
        )
    ).scalar_one()
    assert correct == "B"

    # re-run with one more question: nothing duplicated, the new one is linked at the end
    data["questions"].append(mcq("3", topic=row.title))
    again = await import_paper(db_session, parse_paper(data))
    await db_session.commit()
    assert (again.paper_created, again.created, again.reused, again.linked) == (False, 1, 2, 1)
    assert again.paper_id == first.paper_id


@pytest.mark.db
async def test_unknown_topic_writes_nothing(db_session, topic):
    row, year = topic
    data = paper(year=year, title=f"Import test {year}",
                 questions=[mcq("1", topic=row.title), mcq("2", topic="No such topic zzz")])  # fmt: skip
    with pytest.raises(PaperFileError) as err:
        await import_paper(db_session, parse_paper(data))
    await db_session.rollback()
    assert "No such topic zzz" in err.value.problems[0]
    count = (await db_session.execute(select(Question.id).where(Question.topic_id == row.id))).all()
    assert count == []
