"""Topic-based summaries (SCRUM-37), with the fake LLM and fake retrieval. Owner: Samni."""

import uuid

import pytest

from ai_service.config import get_settings
from ai_service.pipelines.summarization import summarize
from ai_service.pipelines.summarization.chunker import split_for_summary
from ai_service.pipelines.summarization.preprocess import (
    EmptyTextError,
    NotEnglishError,
    NoTextInFileError,
    TextTooLongError,
    UnreadableFileError,
    UnsupportedFileError,
    load_upload_text,
    looks_english,
    preprocess,
)
from ai_service.prompts import render_prompt
from ai_service.providers import set_providers
from ai_service.providers.fakes import FakeLLM, FakeStorage
from ai_service.rag.schemas import RetrievedChunk
from ai_service.schemas.llm_outputs import TopicSummary
from shared.enums import SourceType
from tests.samples import OSMOSIS_NOTES, make_pdf

NOTES = "Osmosis is the movement of water across a partially permeable membrane."


class CountingLLM(FakeLLM):
    """Fake LLM that remembers every prompt it was given."""

    def __init__(self) -> None:
        self.text_prompts: list[str] = []
        self.json_prompts: list[str] = []

    async def generate(self, prompt, **kwargs):  # type: ignore[no-untyped-def]
        self.text_prompts.append(prompt)
        return await super().generate(prompt, **kwargs)

    async def generate_json(self, prompt, schema, **kwargs):  # type: ignore[no-untyped-def]
        self.json_prompts.append(prompt)
        return await super().generate_json(prompt, schema, **kwargs)


def chunk(text: str = "Osmosis needs a partially permeable membrane.") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_title="Unit 2 resource book",
        source_type=SourceType.SYLLABUS,
        text=text,
        page=7,
        score=0.9,
    )


def fake_retrieve(chunks: list[RetrievedChunk]):  # type: ignore[no-untyped-def]
    async def _retrieve(query, unit_id=None, topic_id=None, source_types=None, k=8, **kw):  # type: ignore[no-untyped-def]
        return chunks

    return _retrieve


# ----------------------------------------------------------------- preprocess / chunker
def test_preprocess_cleans_text():
    assert preprocess("  Osmosis   is\r\nwater   movement  ") == "Osmosis is\nwater movement"


def test_preprocess_rejects_empty_notes():
    with pytest.raises(EmptyTextError):
        preprocess("   \n\n  ")


def test_split_for_summary_respects_max_words():
    parts = split_for_summary("word " * 25, max_words=10)
    assert [len(p.split()) for p in parts] == [10, 10, 5]


# ----------------------------------------------------------------- prompt
def test_summarize_topic_prompt_renders():
    prompt = render_prompt(
        "summarization/summarize_topic",
        1,
        topic_title="Osmosis",
        unit_title="Unit 2",
        source_text=NOTES,
        from_parts=False,
        grounded=True,
    )
    assert "Topic: Osmosis" in prompt
    assert "Unit: Unit 2" in prompt
    assert "Cite them as [1]" in prompt
    assert NOTES in prompt


# ----------------------------------------------------------------- pipeline
async def test_short_notes_are_summarised_in_one_call():
    llm = CountingLLM()
    set_providers(llm=llm)
    topic_id = str(uuid.uuid4())

    result = await summarize.run({"topic_title": "Osmosis", "text": NOTES, "topic_id": topic_id})

    TopicSummary.model_validate(result)  # the result has every summary field
    assert result["source"] == "notes"
    assert result["topic_id"] == topic_id
    assert result["citations"] == []
    assert result["prompt_version"] == "summarization/summarize_topic.v1"
    assert llm.text_prompts == []  # no map step for short notes
    [prompt] = llm.json_prompts
    assert NOTES in prompt


async def test_long_notes_use_map_reduce(monkeypatch):
    monkeypatch.setattr(summarize, "MAX_PART_WORDS", 10)
    llm = CountingLLM()
    set_providers(llm=llm)

    result = await summarize.run({"topic_title": "Osmosis", "text": "water " * 25})

    assert result["source"] == "notes"
    assert len(llm.text_prompts) == 3  # one summary per part: 10 + 10 + 5 words
    assert "part 1 of 3" in llm.text_prompts[0]
    [final_prompt] = llm.json_prompts
    assert "Merge them into one summary" in final_prompt


async def test_topic_without_notes_uses_rag_sources(monkeypatch):
    monkeypatch.setattr(summarize, "retrieve", fake_retrieve([chunk()]))
    llm = CountingLLM()
    set_providers(llm=llm)

    result = await summarize.run({"topic_title": "Osmosis"})

    assert result["source"] == "rag"
    [citation] = result["citations"]
    assert citation["ref"] == 1
    assert citation["page"] == 7
    [prompt] = llm.json_prompts
    assert "[1] Unit 2 resource book (p. 7)" in prompt


async def test_topic_without_notes_or_sources_is_refused(monkeypatch):
    monkeypatch.setattr(summarize, "retrieve", fake_retrieve([]))
    with pytest.raises(summarize.NoContextError):
        await summarize.run({"topic_title": "Osmosis"})


async def test_topic_title_is_required():
    with pytest.raises(ValueError, match="topic_title is required"):
        await summarize.run({"text": NOTES})


async def test_invalid_llm_output_is_retried():
    class BadLLM(FakeLLM):
        calls = 0

        async def generate_json(self, prompt, schema, **kwargs):  # type: ignore[no-untyped-def]
            BadLLM.calls += 1
            return schema.model_validate({"title": "missing body_md"})  # raises ValidationError

    set_providers(llm=BadLLM())
    with pytest.raises(RuntimeError, match="invalid after retries"):
        await summarize.run({"topic_title": "Osmosis", "text": NOTES})
    assert BadLLM.calls == summarize.MAX_RETRIES + 1


async def test_summarize_job_through_the_endpoint(ai_client):
    response = await ai_client.post(
        "/jobs/run",
        json={
            "job_id": "j1",
            "job_type": "summarize_upload",
            "payload": {"topic_title": "Osmosis", "text": NOTES},
        },
    )
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["source"] == "notes"
    assert result["prompt_version"] == "summarization/summarize_topic.v1"


# ----------------------------------------------------------------- input checks
def test_preprocess_rejects_too_long_notes(monkeypatch):
    monkeypatch.setattr(get_settings(), "MAX_INPUT_CHARS", 20)
    with pytest.raises(TextTooLongError) as error:
        preprocess(NOTES)
    assert error.value.code == "NOTES_TOO_LONG"


def test_preprocess_rejects_non_english_notes():
    sinhala = "ආශ්‍රැතිය යනු අර්ධ පාරගම්‍ය පටලයක් හරහා ජලය චලනය වීමයි. " * 3
    with pytest.raises(NotEnglishError):
        preprocess(sinhala)


def test_english_check_allows_greek_letters_and_short_text():
    assert looks_english("Alpha (α) and beta (β) glucose form starch and cellulose. " * 3)
    assert looks_english("ජලය")  # too short to judge


# ----------------------------------------------------------------- uploaded files
PDF_PATH = "uploads/test-user/upload.pdf"


async def store(data: bytes) -> FakeStorage:
    storage = FakeStorage()
    await storage.save(PDF_PATH, data, "application/pdf")
    set_providers(storage=storage)
    return storage


async def test_pdf_upload_is_summarised():
    await store(make_pdf(OSMOSIS_NOTES))
    llm = CountingLLM()
    set_providers(llm=llm)

    result = await summarize.run(
        {"topic_title": "Osmosis", "file_path": PDF_PATH, "mime_type": "application/pdf"}
    )

    assert result["source"] == "notes"
    [prompt] = llm.json_prompts
    assert "partially permeable membrane" in prompt  # the PDF text reached the prompt


async def test_pdf_without_text_is_refused():
    await store(make_pdf(""))  # a blank page, like a scan when OCR is not installed
    with pytest.raises(NoTextInFileError) as error:
        await load_upload_text(PDF_PATH, "application/pdf")
    assert error.value.code == "NO_TEXT_IN_FILE"


async def test_broken_pdf_is_refused():
    await store(b"%PDF-1.4 this is not really a pdf")
    with pytest.raises(UnreadableFileError):
        await load_upload_text(PDF_PATH, "application/pdf")


async def test_unsupported_file_type_is_refused():
    with pytest.raises(UnsupportedFileError):
        await load_upload_text("uploads/x.docx", "application/msword")


# ----------------------------------------------------------------- errors over HTTP
async def test_input_errors_answer_422_with_their_code(ai_client):
    response = await ai_client.post(
        "/jobs/run",
        json={
            "job_id": "j1",
            "job_type": "summarize_upload",
            "payload": {"topic_title": "Osmosis", "text": "Page 3 of 10"},  # nothing left
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "EMPTY_NOTES"


async def test_invalid_output_error_does_not_repeat_the_output():
    class BadLLM(FakeLLM):
        async def generate_json(self, prompt, schema, **kwargs):  # type: ignore[no-untyped-def]
            return schema.model_validate({"title": NOTES})  # body_md missing

    set_providers(llm=BadLLM())
    with pytest.raises(RuntimeError) as error:
        await summarize.run({"topic_title": "Osmosis", "text": NOTES})
    assert NOTES not in str(error.value)
    assert "body_md" in str(error.value)
