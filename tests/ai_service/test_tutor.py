"""Ask BrAInBox answers only from approved passages, and says so when it can't."""

import uuid

from ai_service.pipelines.notes import tutor
from ai_service.rag.schemas import RetrievedChunk
from ai_service.schemas.llm_outputs import TutorAnswer
from shared.enums import SourceType


def _chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_title="Unit04 Plants",
        source_type=SourceType.APPROVED_NOTE,
        text="Water moves towards the lower water potential.",
        page=12,
        score=1.0,
    )


class _LLM:
    def __init__(self, answer: TutorAnswer) -> None:
        self.answer = answer

    async def generate_json(self, prompt, schema, **kwargs):  # type: ignore[no-untyped-def]
        assert "Water moves" in prompt
        return self.answer


async def test_no_passages_means_no_ai_answer(monkeypatch) -> None:
    async def nothing(*args, **kwargs):  # type: ignore[no-untyped-def]
        return []

    monkeypatch.setattr(tutor, "retrieve", nothing)
    result = await tutor.ask("What is osmosis?")
    assert result == {"answer": tutor.NOT_FOUND, "grounded": False, "sources": []}


async def test_answer_lists_the_passages_it_used(monkeypatch) -> None:
    async def found(*args, **kwargs):  # type: ignore[no-untyped-def]
        return [_chunk()]

    monkeypatch.setattr(tutor, "retrieve", found)
    answer = TutorAnswer(answer="Towards lower potential.", found_in_sources=True, used_sources=[1])
    monkeypatch.setattr(tutor, "get_llm", lambda: _LLM(answer))
    result = await tutor.ask("What is osmosis?")
    assert result["grounded"] is True
    assert result["sources"] == [{"title": "Unit04 Plants", "page": 12}]


async def test_answer_without_a_source_is_not_shown(monkeypatch) -> None:
    async def found(*args, **kwargs):  # type: ignore[no-untyped-def]
        return [_chunk()]

    monkeypatch.setattr(tutor, "retrieve", found)
    answer = TutorAnswer(answer="From memory.", found_in_sources=True, used_sources=[])
    monkeypatch.setattr(tutor, "get_llm", lambda: _LLM(answer))
    result = await tutor.ask("What is osmosis?")
    assert result["answer"] == tutor.NOT_FOUND
