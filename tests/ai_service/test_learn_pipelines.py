"""Learn tab ai_service pipelines: notes (full/short) and upload summaries, with the mock LLM."""

import io
import json

import pytest

from ai_service.config import get_settings
from ai_service.errors import AIOutputError, UserInputError
from ai_service.pipelines.notes import learn_notes
from ai_service.pipelines.summarization import learn_upload
from ai_service.providers import get_llm_client, set_providers
from ai_service.providers.llm_client import MockLLMClient, build_llm_client
from shared.learn_blocks import BLOCK_TYPES
from tests.samples import OSMOSIS_NOTES, make_pdf

PAYLOAD = {
    "subject": "Biology",
    "unit_number": 6,
    "unit_title": "Genetics",
    "topic_number": "6.1",
    "topic_title": "Mendelian inheritance",
    "syllabus_version": "2025",
    "depth": "standard",
    "include_examples": True,
    "include_past_paper_tips": True,
}


class ScriptedLLM:
    """Answers from a list, one per call, and remembers the prompts."""

    name = "scripted"

    def __init__(self, *answers: str):
        self.answers = list(answers)
        self.prompts: list[str] = []

    async def complete(self, prompt, *, task, meta=None, temperature=None, prompt_name=None):  # type: ignore[no-untyped-def]
        self.prompts.append(prompt)
        return self.answers.pop(0)


# --------------------------------------------------------------------------- llm_client


def test_mock_is_used_without_a_key():
    assert isinstance(get_llm_client(), MockLLMClient)


def test_llm_provider_setting(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "LLM_PROVIDER", "mock")
    assert isinstance(build_llm_client(), MockLLMClient)
    monkeypatch.setattr(settings, "LLM_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "LLM_API_KEY", "")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    assert isinstance(build_llm_client(), MockLLMClient)  # no key -> mock, with a warning
    monkeypatch.setattr(settings, "LLM_PROVIDER", "nope")
    with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
        build_llm_client()


# --------------------------------------------------------------------------- notes


async def test_full_notes_with_the_mock_llm():
    result = await learn_notes.generate(PAYLOAD, short=False)
    assert result["type"] == "full" and result["depth"] == "standard"
    types = {b["type"] for b in result["blocks"]}
    assert {"heading", "paragraph", "definition", "table", "tip"} <= types <= set(BLOCK_TYPES)
    assert result["read_minutes"] >= 1
    assert result["prompt_version"] == "notes/learn_notes.v1"


async def test_toggles_change_the_prompt_and_the_mock_output():
    llm = ScriptedLLM(json.dumps([{"type": "heading", "text": "x"}]))
    set_providers(llm_client=llm)
    await learn_notes.generate(
        {
            **PAYLOAD,
            "depth": "detailed",
            "include_examples": False,
            "include_past_paper_tips": False,
        },
        short=False,
    )
    prompt = llm.prompts[0]
    assert "about 1800 words" in prompt
    assert "Do NOT include worked examples" in prompt and "Do NOT include past-paper tips" in prompt
    assert "Mendelian inheritance" in prompt and "2025 syllabus" in prompt and "Genetics" in prompt

    set_providers(llm_client=MockLLMClient())
    plain = await learn_notes.generate(
        {**PAYLOAD, "include_examples": False, "include_past_paper_tips": False}, short=False
    )
    assert "tip" not in {b["type"] for b in plain["blocks"]}


@pytest.mark.parametrize(
    ("depth", "words"), [("quick", 300), ("standard", 900), ("detailed", 1800)]
)
async def test_depth_sets_the_length(depth, words):
    llm = ScriptedLLM(json.dumps([{"type": "heading", "text": "x"}]))
    set_providers(llm_client=llm)
    await learn_notes.generate({**PAYLOAD, "depth": depth}, short=False)
    assert f"about {words} words" in llm.prompts[0]


async def test_short_notes_have_8_to_15_bullets():
    result = await learn_notes.generate(PAYLOAD, short=True)
    bullets = [i for b in result["blocks"] if b["type"] == "bullet_list" for i in b["items"]]
    assert 8 <= len(bullets) <= 15

    too_many = [{"type": "bullet_list", "items": [f"p{n}" for n in range(20)]}]
    set_providers(llm_client=ScriptedLLM(json.dumps(too_many)))
    result = await learn_notes.generate(PAYLOAD, short=True)
    assert len(result["blocks"][0]["items"]) == 15  # cut, not rejected


async def test_bad_json_is_retried_once():
    good = json.dumps([{"type": "heading", "text": "Fine"}])
    llm = ScriptedLLM("this is not json", good)
    set_providers(llm_client=llm)
    result = await learn_notes.generate(PAYLOAD, short=False)
    assert result["blocks"] == [{"type": "heading", "text": "Fine"}]
    assert len(llm.prompts) == 2 and "could not be used" in llm.prompts[1]


async def test_bad_json_twice_fails_with_a_clear_error():
    llm = ScriptedLLM("nope", '[{"type": "unknown"}]')
    set_providers(llm_client=llm)
    with pytest.raises(AIOutputError, match="invalid notes twice") as info:
        await learn_notes.generate(PAYLOAD, short=False)
    assert info.value.code == "INVALID_AI_OUTPUT"
    assert len(llm.prompts) == 2  # exactly one retry


async def test_too_few_short_bullets_is_retried_then_fails():
    few = json.dumps([{"type": "bullet_list", "items": ["a", "b"]}])
    set_providers(llm_client=ScriptedLLM(few, few))
    with pytest.raises(AIOutputError, match="at least 8"):
        await learn_notes.generate(PAYLOAD, short=True)


async def test_notes_input_errors():
    with pytest.raises(UserInputError, match="topic_title"):
        await learn_notes.generate({}, short=False)
    with pytest.raises(UserInputError) as info:
        await learn_notes.generate({**PAYLOAD, "depth": "huge"}, short=False)
    assert info.value.code == "INVALID_DEPTH"


# --------------------------------------------------------------------------- upload summaries


def make_docx(text: str) -> bytes:
    import docx

    document = docx.Document()
    for line in text.splitlines():
        document.add_paragraph(line)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


@pytest.fixture
def upload_dir(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(get_settings(), "UPLOAD_DIR", str(tmp_path))
    return tmp_path


def _store(folder, name: str, data: bytes) -> str:  # type: ignore[no-untyped-def]
    (folder / "u1").mkdir(exist_ok=True)
    (folder / "u1" / name).write_bytes(data)
    return f"u1/{name}"


@pytest.mark.parametrize(
    ("name", "mime", "data"),
    [
        ("a.pdf", "application/pdf", make_pdf(OSMOSIS_NOTES)),
        ("a.docx", learn_upload.DOCX_MIME, make_docx(OSMOSIS_NOTES)),
        ("a.txt", "text/plain", OSMOSIS_NOTES.encode()),
    ],
    ids=["pdf", "docx", "txt"],
)
async def test_summary_of_each_file_type(upload_dir, name, mime, data):
    path = _store(upload_dir, name, data)
    result = await learn_upload.run(
        {
            "storage_path": path,
            "mime_type": mime,
            "summary_length": "short",
            "topic_title": "Osmosis",
        }
    )
    assert "Osmosis" in result["summary"]
    assert 5 <= len(result["key_points"]) <= 10
    assert "water potential" in result["extracted_text"]
    assert result["parts"] == 1


async def test_long_text_is_chunked_then_combined(upload_dir):
    long_text = ("Osmosis moves water across a partially permeable membrane. " * 300).encode()
    path = _store(upload_dir, "long.txt", long_text)
    llm = ScriptedLLM(
        "part one summary",
        "part two summary",
        json.dumps({"summary": "A combined summary of both parts.", "key_points": list("abcde")}),
    )
    set_providers(llm_client=llm)
    result = await learn_upload.run(
        {"storage_path": path, "mime_type": "text/plain", "summary_length": "detailed"}
    )
    assert result["parts"] == 2 and len(llm.prompts) == 3
    assert "Part 1:" in llm.prompts[2] and "about 500 words" in llm.prompts[2]


async def test_summary_length_sets_the_target(upload_dir):
    path = _store(upload_dir, "a.txt", OSMOSIS_NOTES.encode())
    answer = json.dumps({"summary": "x" * 30, "key_points": list("abcdefghijkl")})
    llm = ScriptedLLM(answer)
    set_providers(llm_client=llm)
    result = await learn_upload.run(
        {"storage_path": path, "mime_type": "text/plain", "summary_length": "medium"}
    )
    assert "about 250 words" in llm.prompts[0]
    assert len(result["key_points"]) == 10  # more than 10 are cut


async def test_invalid_summary_twice_fails(upload_dir):
    path = _store(upload_dir, "a.txt", OSMOSIS_NOTES.encode())
    set_providers(llm_client=ScriptedLLM("no", json.dumps({"summary": "short", "key_points": []})))
    with pytest.raises(AIOutputError):
        await learn_upload.run(
            {"storage_path": path, "mime_type": "text/plain", "summary_length": "short"}
        )


async def test_image_without_ocr_fails_clearly(upload_dir, monkeypatch):
    monkeypatch.setattr(learn_upload, "ocr_available", lambda: False)
    path = _store(upload_dir, "a.png", b"\x89PNG\r\n\x1a\nxxxx")
    with pytest.raises(UserInputError, match="OCR not available") as info:
        await learn_upload.run(
            {"storage_path": path, "mime_type": "image/png", "summary_length": "short"}
        )
    assert info.value.code == "OCR_NOT_AVAILABLE"


async def test_image_with_ocr(upload_dir, monkeypatch):
    monkeypatch.setattr(learn_upload, "ocr_available", lambda: True)
    monkeypatch.setattr(learn_upload, "_ocr_image", lambda data: OSMOSIS_NOTES)
    path = _store(upload_dir, "a.jpg", b"\xff\xd8\xffxxxx")
    result = await learn_upload.run(
        {"storage_path": path, "mime_type": "image/jpeg", "summary_length": "short"}
    )
    assert "water potential" in result["extracted_text"]


@pytest.mark.parametrize(
    ("name", "mime", "data", "code"),
    [
        ("e.txt", "text/plain", b"   ", "EMPTY_NOTES"),
        ("b.pdf", "application/pdf", b"%PDF-broken", "UNREADABLE_FILE"),
        ("x.exe", "application/x-msdownload", b"MZ", "UNSUPPORTED_FILE_TYPE"),
    ],
    ids=["empty", "broken-pdf", "exe"],
)
async def test_unreadable_files(upload_dir, name, mime, data, code):
    path = _store(upload_dir, name, data)
    with pytest.raises(UserInputError) as info:
        await learn_upload.run({"storage_path": path, "mime_type": mime, "summary_length": "short"})
    assert info.value.code == code


async def test_missing_file_and_path_escape(upload_dir):
    with pytest.raises(UserInputError, match="not found"):
        await learn_upload.run(
            {"storage_path": "u1/none.txt", "mime_type": "text/plain", "summary_length": "short"}
        )
    with pytest.raises(UserInputError, match="Invalid upload path"):
        await learn_upload.run(
            {"storage_path": "../../.env", "mime_type": "text/plain", "summary_length": "short"}
        )
