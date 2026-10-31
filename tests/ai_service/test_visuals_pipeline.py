"""Tests for the visuals pipeline (ai_service/pipelines/visuals). Owner: Mogith.

Fake providers only: no API keys, no network. Kroki and Cloudflare are replaced by
httpx.MockTransport, so the real HTTP code runs without leaving the computer.
"""

import base64
import io
import json
import uuid
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from PIL import Image

from ai_service.config import get_settings
from ai_service.errors import UserInputError
from ai_service.pipelines.visuals import decide_visual, illustration
from ai_service.pipelines.visuals.diagram_mermaid import (
    MAX_MERMAID_CHARS,
    strip_fences,
    validate_mermaid,
)
from ai_service.providers import (
    get_image_generator,
    get_storage,
    reset_providers,
    set_providers,
)
from ai_service.providers.diagram_renderer import FakeDiagramRenderer, KrokiRenderer
from ai_service.providers.fakes import FakeImageGenerator, FakeLLM
from ai_service.providers.image_gen import CloudflareImageGenerator, GeminiImageGenerator
from ai_service.rag.context_builder import BuiltContext
from ai_service.schemas.llm_outputs import VisualDecision

FLOWCHART = 'flowchart LR\n  A["1. Filtration"] --> B["2. Reabsorption"]'


def png_bytes(width: int = 40, height: int = 30, fmt: str = "PNG") -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(out, format=fmt)
    return out.getvalue()


def decision(**changes: Any) -> dict[str, Any]:
    """A valid LLM answer; change any field with keyword arguments."""
    return {**VisualDecision.fake_example(), **changes}


class ScriptedLLM(FakeLLM):
    """Returns the given answers one after the other (the last one repeats) and keeps prompts."""

    def __init__(self, *answers: dict[str, Any]):
        self.answers = list(answers)
        self.prompts: list[str] = []

    async def generate_json(self, prompt, schema, **kwargs):  # type: ignore[no-untyped-def]
        self.prompts.append(prompt)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        return schema.model_validate(answer)


class RecordingImages(FakeImageGenerator):
    def __init__(self, image: bytes):
        self.image = image
        self.prompts: list[str] = []

    async def generate_image(self, prompt: str) -> bytes:
        self.prompts.append(prompt)
        return self.image


def payload(**changes: Any) -> dict[str, Any]:
    return {
        "visual_id": str(uuid.uuid4()),
        "prompt": "Show how urine is formed",
        "visual_type": "process",
        "style": "flat_colour",
        "topic_title": "Excretion",
        "topic_id": str(uuid.uuid4()),
        **changes,
    }


@pytest.fixture(autouse=True)
def no_rag(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """No database search: RAG returns one fixed fact. Returns the queries it was asked."""
    queries: list[str] = []

    async def fake_context(query, topic_id):  # type: ignore[no-untyped-def]
        queries.append(query)
        return BuiltContext(text="[1] FACT-123: urine is formed in the nephron.", citations=[])

    monkeypatch.setattr(decide_visual, "gather_context", fake_context)
    return queries


# --------------------------------------------------------------------------- validate_mermaid


@pytest.mark.parametrize(
    "raw",
    [
        f"```mermaid\n{FLOWCHART}\n```",
        f"```\n{FLOWCHART}\n```",
        f"~~~mermaid\n{FLOWCHART}\n~~~",
        f"\n\n  {FLOWCHART}  \n",
    ],
)
def test_validate_mermaid_strips_fences(raw: str) -> None:
    assert validate_mermaid(raw) == FLOWCHART


@pytest.mark.parametrize(
    "code",
    [
        "graph TD\n A --> B",
        "sequenceDiagram\n A->>B: hi",
        "stateDiagram-v2\n [*] --> A",
        "%% a comment first\nflowchart TB\n A --> B",
    ],
)
def test_validate_mermaid_accepts_known_types(code: str) -> None:
    assert validate_mermaid(code) == code


@pytest.mark.parametrize(
    "code",
    [
        "pie title Pets\n 'Dogs' : 3",  # a real Mermaid type we do not allow
        "graphical nonsense",  # starts like "graph" but is not
        "Here is your diagram:\nflowchart LR\n A --> B",
        "",
        None,
        "```mermaid\n```",
    ],
)
def test_validate_mermaid_rejects_unknown_or_empty(code: str | None) -> None:
    with pytest.raises(ValueError):
        validate_mermaid(code)


def test_validate_mermaid_has_a_size_limit() -> None:
    too_long = "flowchart LR\n" + "A --> B\n" * (MAX_MERMAID_CHARS // 8 + 1)
    assert len(too_long) > MAX_MERMAID_CHARS
    with pytest.raises(ValueError, match="longer than"):
        validate_mermaid(too_long)


def test_validate_mermaid_rejects_click_lines() -> None:
    with pytest.raises(ValueError, match="click"):
        validate_mermaid('flowchart LR\n A --> B\n click A "https://evil.example"')


def test_strip_fences_leaves_plain_code_alone() -> None:
    assert strip_fences("flowchart LR") == "flowchart LR"


# --------------------------------------------------------------------------- Kroki


def kroki_transport(requests: list[httpx.Request], response: httpx.Response):  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return response

    return httpx.MockTransport(handler)


async def test_kroki_posts_mermaid_as_text_and_returns_png() -> None:
    requests: list[httpx.Request] = []
    png = png_bytes()
    renderer = KrokiRenderer(
        "https://kroki.test/", transport=kroki_transport(requests, httpx.Response(200, content=png))
    )
    assert await renderer.render_png(FLOWCHART) == png
    [request] = requests
    assert str(request.url) == "https://kroki.test/mermaid/png"
    assert request.headers["content-type"] == "text/plain"
    assert request.content.decode() == FLOWCHART


@pytest.mark.parametrize(
    "response",
    [httpx.Response(503, text="busy"), httpx.Response(200, content=b"<svg>not a png</svg>")],
)
async def test_kroki_problems_return_none(response: httpx.Response) -> None:
    renderer = KrokiRenderer("https://kroki.test", transport=kroki_transport([], response))
    assert await renderer.render_png(FLOWCHART) is None


async def test_kroki_unreachable_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host", request=request)

    renderer = KrokiRenderer("https://kroki.test", transport=httpx.MockTransport(handler))
    assert await renderer.render_png(FLOWCHART) is None


# --------------------------------------------------------------------------- pipeline


async def test_mermaid_visual_is_rendered_and_stored() -> None:
    requests: list[httpx.Request] = []
    png = png_bytes(120, 80)
    set_providers(
        llm=ScriptedLLM(decision(kind="flowchart", mermaid_code=f"```mermaid\n{FLOWCHART}\n```")),
        diagram=KrokiRenderer(
            "https://kroki.test",
            transport=kroki_transport(requests, httpx.Response(200, content=png)),
        ),
    )
    job = payload()
    result = await decide_visual.run(job)

    path = f"visuals/{job['topic_id']}/{job['visual_id']}.png"
    assert result["visual_id"] == job["visual_id"]
    assert result["kind"] == "flowchart"
    assert result["mermaid_code"] == FLOWCHART  # fences removed
    assert result["image_path"] == path
    assert (result["width"], result["height"]) == (120, 80)
    assert get_storage().files[path] == png  # type: ignore[attr-defined]
    assert requests[0].content.decode() == FLOWCHART
    assert result["safety_passed"] is True
    assert result["prompt_version"] == "visuals/decide_visual.v2"
    assert result["style"] == "flat_colour"
    # Mermaid labels have no position: the app lists them under the diagram
    assert [label["number"] for label in result["labels"]] == [1, 2, 3]
    assert all(label["x"] is None and label["y"] is None for label in result["labels"])


async def test_kroki_down_keeps_the_mermaid_code() -> None:
    renderer = FakeDiagramRenderer()
    renderer.down = True
    set_providers(llm=ScriptedLLM(decision()), diagram=renderer)
    result = await decide_visual.run(payload())
    assert result["mermaid_code"].startswith("flowchart LR")
    assert result["image_path"] is None
    assert result["width"] is None and result["height"] is None
    assert get_storage().files == {}  # type: ignore[attr-defined]


async def test_invalid_mermaid_is_retried() -> None:
    llm = ScriptedLLM(decision(mermaid_code="pie title x"), decision(mermaid_code=FLOWCHART))
    set_providers(llm=llm)
    result = await decide_visual.run(payload())
    assert result["mermaid_code"] == FLOWCHART
    assert len(llm.prompts) == 2


async def test_gives_up_after_retries() -> None:
    llm = ScriptedLLM(decision(mermaid_code="not mermaid"))
    set_providers(llm=llm)
    with pytest.raises(RuntimeError, match="invalid after retries"):
        await decide_visual.run(payload())
    assert len(llm.prompts) == decide_visual.MAX_RETRIES + 1


async def test_illustration_uses_style_and_no_text_rule() -> None:
    images = RecordingImages(png_bytes(64, 48, fmt="JPEG"))  # providers may send JPEG
    labels = [
        {"number": 7, "name": "Nucleus", "description": "Holds the DNA.", "x": 0.4, "y": 0.5},
        {"number": 9, "name": "Cell wall", "description": "Made of cellulose.", "x": 1.4, "y": -2},
    ]
    set_providers(
        llm=ScriptedLLM(
            decision(
                kind="illustration",
                mermaid_code=None,
                image_prompt="A plant cell cut in half",
                labels=labels,
            )
        ),
        image=images,
    )
    job = payload(visual_type="structure", style="cross_section", topic_id=None)
    result = await decide_visual.run(job)

    [image_prompt] = images.prompts
    assert image_prompt.startswith("A plant cell cut in half")
    assert illustration.STYLE_PROMPTS["cross_section"] in image_prompt
    assert illustration.NO_TEXT in image_prompt
    assert result["kind"] == "illustration"
    assert result["mermaid_code"] is None
    assert result["image_path"] == f"visuals/general/{job['visual_id']}.png"
    assert (result["width"], result["height"]) == (64, 48)
    stored = get_storage().files[result["image_path"]]  # type: ignore[attr-defined]
    assert stored.startswith(b"\x89PNG")  # converted from JPEG
    # renumbered 1, 2 and positions kept inside 0-1
    assert [(lb["number"], lb["x"], lb["y"]) for lb in result["labels"]] == [
        (1, 0.4, 0.5),
        (2, 1.0, 0.0),
    ]


async def test_not_biology_is_refused() -> None:
    set_providers(llm=ScriptedLLM(decision(is_biology=False, mermaid_code=None)))
    with pytest.raises(UserInputError) as caught:
        await decide_visual.run(payload(prompt="Draw a cartoon of a footballer"))
    assert caught.value.code == "NOT_BIOLOGY"
    assert caught.value.message == "I can only draw Biology visuals."


@pytest.mark.parametrize(
    "changes",
    [{"prompt": "   "}, {"visual_id": None}, {"visual_type": "map"}, {"style": "neon"}],
)
async def test_bad_payload_is_an_input_error(changes: dict[str, Any]) -> None:
    with pytest.raises(UserInputError):
        await decide_visual.run(payload(**changes))


async def test_prompt_is_grounded_with_rag(no_rag: list[str]) -> None:
    llm = ScriptedLLM(decision())
    set_providers(llm=llm)
    await decide_visual.run(payload())
    assert no_rag == ["Excretion Show how urine is formed"]
    assert "FACT-123" in llm.prompts[0]
    assert "Show how urine is formed" in llm.prompts[0]
    assert "a flowchart of the steps" in llm.prompts[0]  # the visual_type hint


async def test_rag_failure_does_not_stop_the_visual(monkeypatch: pytest.MonkeyPatch) -> None:
    async def broken(query, topic_id):  # type: ignore[no-untyped-def]
        raise ConnectionError("database down")

    monkeypatch.setattr(decide_visual, "gather_context", broken)
    llm = ScriptedLLM(decision())
    set_providers(llm=llm)
    result = await decide_visual.run(payload())
    assert result["kind"] == "diagram"
    assert "No syllabus extract was found" in llm.prompts[0]


def test_to_png_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        illustration.to_png(b"definitely not an image")


# --------------------------------------------------------------------------- image providers


async def test_cloudflare_reads_base64_image() -> None:
    requests: list[httpx.Request] = []
    image = png_bytes(8, 8, fmt="JPEG")
    body = {"result": {"image": base64.b64encode(image).decode()}, "success": True}

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=body)

    generator = CloudflareImageGenerator(
        "acc-1", "token-1", "@cf/black-forest-labs/flux-1-schnell",
        transport=httpx.MockTransport(handler),
    )  # fmt: skip
    assert await generator.generate_image("a leaf") == image
    [request] = requests
    assert str(request.url) == (
        "https://api.cloudflare.com/client/v4/accounts/acc-1/ai/run/"
        "@cf/black-forest-labs/flux-1-schnell"
    )
    assert request.headers["authorization"] == "Bearer token-1"
    assert json.loads(request.content) == {"prompt": "a leaf", "steps": 4}


async def test_cloudflare_without_image_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": {}, "success": True})

    generator = CloudflareImageGenerator("a", "t", "m", transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError):
        await generator.generate_image("a leaf")


async def test_gemini_image_reads_inline_data() -> None:
    image = png_bytes(4, 4)
    calls: list[dict[str, Any]] = []

    async def generate_content(**kwargs):  # type: ignore[no-untyped-def]
        calls.append(kwargs)
        part_text = SimpleNamespace(inline_data=None)
        part_image = SimpleNamespace(inline_data=SimpleNamespace(data=image, mime_type="image/png"))
        content = SimpleNamespace(parts=[part_text, part_image])
        return SimpleNamespace(candidates=[SimpleNamespace(content=content)])

    generator = GeminiImageGenerator.__new__(GeminiImageGenerator)  # skip the real SDK client
    generator.model = "gemini-2.5-flash-image"
    generator.daily_limit = 0  # no cap -> no database needed
    generator._client = SimpleNamespace(  # type: ignore[attr-defined]
        aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    )
    assert await generator.generate_image("a leaf") == image
    assert calls[0]["model"] == "gemini-2.5-flash-image"
    assert calls[0]["config"].response_modalities == ["IMAGE"]


def test_image_provider_is_chosen_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "USE_FAKE_AI", False)
    monkeypatch.setattr(settings, "IMAGE_PROVIDER", "cloudflare")
    monkeypatch.setattr(settings, "CLOUDFLARE_ACCOUNT_ID", "acc")
    monkeypatch.setattr(settings, "CLOUDFLARE_API_TOKEN", "")
    assert isinstance(get_image_generator(), FakeImageGenerator)  # no token -> fake

    reset_providers()  # forget the cached image provider
    monkeypatch.setattr(settings, "CLOUDFLARE_API_TOKEN", "tok")
    assert isinstance(get_image_generator(), CloudflareImageGenerator)

    reset_providers()
    monkeypatch.setattr(settings, "IMAGE_PROVIDER", "paintbrush")
    with pytest.raises(ValueError, match="IMAGE_PROVIDER"):
        get_image_generator()


def test_defaults_are_free() -> None:
    settings = get_settings()
    assert settings.IMAGE_PROVIDER == "cloudflare"  # free daily allowance
    assert settings.IMAGE_MODEL == "gemini-2.5-flash-image"  # only if IMAGE_PROVIDER=gemini
    assert settings.KROKI_URL == "https://kroki.io"
