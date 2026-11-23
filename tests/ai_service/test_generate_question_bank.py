"""The question generator copes with a busy Gemini and never claims a check it didn't do."""

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import generate_question_bank as generator  # noqa: E402

from shared.enums import QuestionType  # noqa: E402

TOPIC = generator.TopicInfo(uuid.uuid4(), "Osmosis", 1, uuid.uuid4(), 4)
ARGS = argparse.Namespace(mcq_per_topic=3, structured_per_topic=1, essay_per_topic=1)
BUSY = RuntimeError("Gemini failed after retries: 503")
ITEM = {"question": "Q?", "options": ["A", "B"], "correct_answer": "A"}


class _Session:
    def __init__(self) -> None:
        self.rollbacks = 0

    async def rollback(self) -> None:
        self.rollbacks += 1


@pytest.fixture
def sleeps(monkeypatch) -> list[float]:  # type: ignore[no-untyped-def]
    waited: list[float] = []

    async def no_wait(seconds: float) -> None:
        waited.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", no_wait)
    return waited


def _review(**blind) -> dict:  # type: ignore[no-untyped-def]
    return {"checks": {"blind_review": blind}}


def test_unchecked_answer_is_not_shown_as_passed() -> None:
    checks = generator.checks_for_review(QuestionType.MCQ, answer_confirmed=False)
    assert checks["single_correct_answer"]["result"] == "review"
    assert (
        generator.checks_for_review(QuestionType.MCQ)["single_correct_answer"]["result"] == "pass"
    )


async def test_busy_reviewer_gets_a_second_try(sleeps, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    async def agrees(item):  # type: ignore[no-untyped-def]
        return {"passed": True}

    monkeypatch.setattr(generator, "blind_check", agrees)
    review = _review(passed=None, skipped="reviewer unavailable")
    assert await generator.confirm_answer(ITEM, review) is True
    assert sleeps == [generator.REVIEWER_WAIT_SECONDS]


async def test_reviewer_results(sleeps, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    async def still_busy(item):  # type: ignore[no-untyped-def]
        return {"passed": None, "skipped": "reviewer unavailable"}

    async def disagrees(item):  # type: ignore[no-untyped-def]
        return {"passed": False}

    busy_review = _review(passed=None, skipped="reviewer unavailable")
    monkeypatch.setattr(generator, "blind_check", still_busy)
    assert await generator.confirm_answer(ITEM, busy_review) is False
    monkeypatch.setattr(generator, "blind_check", disagrees)
    assert await generator.confirm_answer(ITEM, busy_review) is None


async def test_topic_is_retried_after_a_busy_error(sleeps, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls = {"n": 0}

    async def flaky(session, topic, args):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 1:
            raise BUSY
        return 3, 2

    monkeypatch.setattr(generator, "process_topic", flaky)
    session = _Session()
    assert await generator.process_with_waits(session, TOPIC, ARGS) == (3, 2)
    assert sleeps == [generator.BUSY_WAIT_SECONDS]
    assert session.rollbacks == 1


async def test_run_stops_when_gemini_stays_busy(sleeps, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls = {"n": 0}

    async def always_busy(session, topic, args):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        raise BUSY

    monkeypatch.setattr(generator, "process_topic", always_busy)
    with pytest.raises(generator.GeminiStillBusy):
        await generator.process_with_waits(_Session(), TOPIC, ARGS)
    assert calls["n"] == generator.BUSY_ROUNDS
    assert len(sleeps) == generator.BUSY_ROUNDS - 1


async def test_other_errors_are_not_retried(sleeps, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    async def broken(session, topic, args):  # type: ignore[no-untyped-def]
        raise RuntimeError("LLM output was invalid after retries")

    monkeypatch.setattr(generator, "process_topic", broken)
    with pytest.raises(RuntimeError, match="invalid"):
        await generator.process_with_waits(_Session(), TOPIC, ARGS)
    assert sleeps == []
