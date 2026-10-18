"""Question generation, paper building and explanations, with the fake LLM and fake retrieval."""

import uuid

import pytest
from pydantic import BaseModel

from ai_service.pipelines.questions import explain_answers, generate_questions, paper_builder
from ai_service.prompts import render_prompt
from ai_service.providers import set_providers
from ai_service.providers.fakes import FakeLLM
from ai_service.rag.schemas import RetrievedChunk
from ai_service.schemas.llm_outputs import AnswerExplanationSet, GeneratedMCQSet
from shared.enums import SourceType


def chunk(text: str = "Mitochondria are the site of aerobic respiration.") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_title="Unit 2 resource book",
        source_type=SourceType.SYLLABUS,
        text=text,
        page=12,
        score=0.9,
    )


def fake_retrieve(chunks: list[RetrievedChunk]):  # type: ignore[no-untyped-def]
    async def _retrieve(query, unit_id=None, topic_id=None, source_types=None, k=8, **kw):  # type: ignore[no-untyped-def]
        return chunks

    return _retrieve


def test_split_counts_shares_questions_evenly():
    assert paper_builder.split_counts(7, 3) == [3, 2, 2]
    assert paper_builder.split_counts(2, 3) == [1, 1, 0]
    assert sum(paper_builder.split_counts(20, 6)) == 20


async def test_build_paper_with_fake_llm(monkeypatch):
    monkeypatch.setattr(generate_questions, "retrieve", fake_retrieve([chunk()]))
    topic_id = str(uuid.uuid4())
    result = await paper_builder.run(
        {
            "num_questions": 1,
            "topics": [{"topic_id": topic_id, "title": "Cell structure", "unit_id": None}],
        }
    )
    assert result["warnings"] == []
    assert result["prompt_version"] == "questions/generate_mcq.v2"
    [question] = result["questions"]
    assert question["topic_id"] == topic_id
    assert question["correct_answer"] in question["options"]
    assert len(question["chunk_ids"]) == 1


async def test_topic_without_sources_becomes_a_warning(monkeypatch):
    monkeypatch.setattr(generate_questions, "retrieve", fake_retrieve([]))
    result = await paper_builder.run(
        {"num_questions": 2, "topics": [{"topic_id": "t1", "title": "Genetics"}]}
    )
    assert result["questions"] == []
    assert result["warnings"] == ["Genetics: No syllabus content found for topic 'Genetics'"]


async def test_invalid_llm_output_is_retried(monkeypatch):
    monkeypatch.setattr(generate_questions, "retrieve", fake_retrieve([chunk()]))

    class BadLLM(FakeLLM):
        calls = 0

        async def generate_json(self, prompt, schema, **kwargs):  # type: ignore[no-untyped-def]
            BadLLM.calls += 1
            # answer is not one of the options -> ValidationError, like a bad Gemini answer
            return GeneratedMCQSet.model_validate(
                {
                    "questions": [
                        {"question": "?", "options": ["a", "b", "c", "d"], "correct_answer": "x"}
                    ]
                }
            )

    set_providers(llm=BadLLM())
    with pytest.raises(RuntimeError, match="invalid after retries"):
        await generate_questions.generate_for_topic("Cells", 1)
    assert BadLLM.calls == generate_questions.MAX_RETRIES + 1


def test_generate_prompt_includes_examples():
    prompt = render_prompt(
        "questions/generate_mcq",
        2,
        topic_title="Photosynthesis",
        count=3,
        context="[1] Light reactions happen in the thylakoids.",
        examples=[{"question": "Where?", "options": ["A1", "B1"], "correct_answer": "A1"}],
    )
    assert 'Write 3 NEW multiple-choice questions on the topic "Photosynthesis"' in prompt
    assert "Options: A1 | B1" in prompt


async def test_explanations_only_for_requested_questions(monkeypatch):
    monkeypatch.setattr(explain_answers, "retrieve", fake_retrieve([chunk()]))

    class ExplainLLM(FakeLLM):
        async def generate_json(self, prompt, schema: type[BaseModel], **kwargs):  # type: ignore[no-untyped-def]
            assert "Student's answer: not answered" in prompt
            return AnswerExplanationSet(
                items=[
                    {"question_id": "q1", "explanation": "ATP is made in mitochondria."},
                    {"question_id": "made-up", "explanation": "ignored"},
                ]
            )

    set_providers(llm=ExplainLLM())
    items = [
        {
            "question_id": "q1",
            "question": "Where?",
            "correct_answer": "Mitochondrion",
            "selected_option": None,
        }
    ]
    assert await explain_answers.explain_answers(items) == {"q1": "ATP is made in mitochondria."}


async def test_explain_endpoint_never_fails(ai_client, monkeypatch):
    async def broken_retrieve(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise ConnectionError("database down")

    monkeypatch.setattr(explain_answers, "retrieve", broken_retrieve)
    response = await ai_client.post(
        "/sync/explain-mcq",
        json={
            "items": [
                {"question_id": "q1", "question": "Where?", "correct_answer": "Mitochondrion"}
            ]
        },
    )
    assert response.status_code == 200
    assert response.json()["result"] == {"explanations": {}}
