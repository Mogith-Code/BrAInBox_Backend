"""BUILD_PAPER for model paper blueprints (paper_builder.build_from_gaps / fill_gap) and the
written-question quality rules. No database: generation and review are stubbed."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from ai_service.pipelines.questions import paper_builder, quality_checks
from ai_service.schemas.llm_outputs import (
    GeneratedMCQ,
    GeneratedWrittenQuestion,
    GeneratedWrittenSet,
)

OPTIONS = ["Ribosome", "Mitochondrion", "Golgi apparatus", "Lysosome", "Nucleus"]
NO_CONTEXT = SimpleNamespace(citations=[])


def mcq(n: int) -> GeneratedMCQ:
    return GeneratedMCQ(question=f"Q{n}?", options=OPTIONS, correct_answer="Mitochondrion")


def written(n: int, marks: int = 4) -> GeneratedWrittenQuestion:
    return GeneratedWrittenQuestion.model_validate(
        {
            "question": f"Explain {n}.",
            "marks": marks,
            "model_answer": "Because...",
            "points": [{"text": f"p{i}", "marks": 1, "keywords": ["k"]} for i in range(marks)],
        }
    )


@pytest.fixture
def generator(monkeypatch):  # type: ignore[no-untyped-def]
    """Counts generate calls; questions are numbered so each call gives new ones."""
    calls: list[tuple[str, int]] = []
    counter = iter(range(1, 1000))

    async def fake_mcq(title, count, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(("mcq", count))
        assert kwargs["difficulty"] in ("easy", "medium", "hard")
        return [mcq(next(counter)) for _ in range(count)], NO_CONTEXT

    async def fake_written(title, count, *, question_type, difficulty, unit_id):  # type: ignore[no-untyped-def]
        calls.append((question_type, count))
        return [written(next(counter)) for _ in range(count)], NO_CONTEXT

    monkeypatch.setattr(paper_builder, "generate_for_topic", fake_mcq)
    monkeypatch.setattr(paper_builder, "generate_written", fake_written)
    return calls


def reviewer(monkeypatch, reject):  # type: ignore[no-untyped-def]
    """Replace both reviews: `reject(question)` -> True rejects it."""

    async def review(questions, existing):  # type: ignore[no-untyped-def]
        return [
            {"passed": not reject(q), "issues": ["bad"] if reject(q) else [], "checks": {}}
            for q in questions
        ]

    monkeypatch.setattr(quality_checks, "review_questions", review)
    monkeypatch.setattr(quality_checks, "review_written", review)


GAP = {"question_type": "mcq", "difficulty": "hard", "count": 3, "title": "Cells", "unit_id": None}


async def test_a_rejected_question_is_regenerated_once(generator, monkeypatch):
    reviewer(monkeypatch, lambda q: q["question"] == "Q2?")  # only the 2nd one is bad
    warnings: list[str] = []
    kept = await paper_builder.fill_gap(GAP, [], warnings)
    assert [q["question"] for q in kept] == ["Q1?", "Q3?", "Q4?"]  # Q4 replaced Q2
    assert generator == [("mcq", 3), ("mcq", 1)]  # one retry, only for the rejected one
    assert warnings == []
    assert kept[0]["question_type"] == "mcq" and kept[0]["difficulty"] == "hard"


async def test_rejected_twice_is_dropped(generator, monkeypatch):
    reviewer(monkeypatch, lambda q: q["question"] in ("Q2?", "Q4?"))  # the retry is bad too
    warnings: list[str] = []
    kept = await paper_builder.fill_gap(GAP, [], warnings)
    assert [q["question"] for q in kept] == ["Q1?", "Q3?"]
    assert generator == [("mcq", 3), ("mcq", 1)]  # never a second retry
    assert len(warnings) == 1 and "failed the quality checks twice" in warnings[0]


async def test_reviewer_down_keeps_the_questions(generator, monkeypatch):
    async def broken(questions, existing):  # type: ignore[no-untyped-def]
        raise RuntimeError("down")

    monkeypatch.setattr(quality_checks, "review_written", broken)
    warnings: list[str] = []
    gap = {**GAP, "question_type": "essay", "count": 2}
    kept = await paper_builder.fill_gap(gap, [], warnings)
    assert len(kept) == 2 and warnings == [paper_builder.REVIEWER_DOWN]
    assert kept[0]["points"] and kept[0]["model_answer"]


async def test_build_from_gaps_fills_every_type(generator, monkeypatch):
    reviewer(monkeypatch, lambda q: False)
    result = await paper_builder.run(
        {
            "gaps": [
                {**GAP, "count": 2},
                {**GAP, "question_type": "structured", "count": 1},
                {**GAP, "question_type": "essay", "count": 0},  # nothing to do
            ],
            "existing": ["Bank question"],
        }
    )
    assert [q["question_type"] for q in result["questions"]] == ["mcq", "mcq", "structured"]
    assert result["warnings"] == []
    assert {"questions/generate_mcq.v3", "questions/generate_written.v1"} == set(
        result["prompt_versions"]
    )


async def test_a_failing_gap_is_a_warning(monkeypatch):
    async def no_context(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise ValueError("No syllabus content found for topic 'Cells'")

    monkeypatch.setattr(paper_builder, "generate_for_topic", no_context)
    result = await paper_builder.build_from_gaps({"gaps": [GAP]})
    assert result["questions"] == []
    assert "No syllabus content" in result["warnings"][0]


# --------------------------------------------------------------------------- written rules


def test_written_rules():
    good = {**written(1).model_dump(), "question_type": "structured"}
    assert quality_checks.written_rule_issues(good) == []
    bad = {**good, "model_answer": "", "points": [{"text": "x", "marks": 4, "keywords": []}]}
    issues = " ".join(quality_checks.written_rule_issues(bad))
    assert "model answer" in issues and "at least 2 points" in issues and "keyword" in issues
    essay = {**good, "question_type": "essay"}  # 4 marks is too few for an essay
    assert any("5-20 marks" in i for i in quality_checks.written_rule_issues(essay))


def test_written_schema_checks_the_marks_add_up():
    assert GeneratedWrittenSet.model_validate(GeneratedWrittenSet.fake_example()).questions
    with pytest.raises(ValidationError):
        GeneratedWrittenQuestion.model_validate(
            {"question": "q", "marks": 5, "model_answer": "a",
             "points": [{"text": "p", "marks": 1, "keywords": ["k"]}]}
        )  # fmt: skip


async def test_review_written_flags_duplicates(monkeypatch):
    async def duplicates(stems, existing):  # type: ignore[no-untyped-def]
        return [{"passed": False, "similarity": 0.99, "similar_to": existing[0]} for _ in stems]

    monkeypatch.setattr(quality_checks, "duplicate_checks", duplicates)
    q = {**written(1).model_dump(), "question_type": "structured"}
    [review] = await quality_checks.review_written([q], ["Explain 1."])
    assert review["passed"] is False and "almost the same" in review["issues"][0]


@pytest.mark.parametrize("kind", ["structured", "essay"])
def test_new_prompts_render(kind):
    from ai_service.prompts import render_prompt

    mcq_prompt = render_prompt("questions/generate_mcq", 3, topic_title="Cells", count=2,
                               difficulty="hard", context="ctx", examples=[])  # fmt: skip
    assert "Difficulty: hard." in mcq_prompt and "exactly 5 options" in mcq_prompt
    written_prompt = render_prompt("questions/generate_written", 1, topic_title="Cells",
                                   count=1, question_type=kind, difficulty="easy", context="ctx")  # fmt: skip
    assert f"{kind} question" in written_prompt and "add up EXACTLY" in written_prompt
    assert ("Part B" in written_prompt) == (kind == "essay")
