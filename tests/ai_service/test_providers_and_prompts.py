"""Fake providers are deterministic, and every prompt template is valid Jinja2."""

import math

from jinja2 import Environment, FileSystemLoader

from ai_service.prompts import PROMPTS_DIR, list_prompts, render_prompt
from ai_service.providers import get_embedder, get_llm
from ai_service.providers.fakes import FakeEmbedder
from ai_service.schemas.llm_outputs import GeneratedMCQ, VisualDecision


async def test_fake_embedder_is_deterministic_and_normalised():
    embedder = FakeEmbedder(dim=768)
    [a1], [a2] = (
        await embedder.embed(["active transport"]),
        await embedder.embed(["active transport"]),
    )
    assert a1 == a2
    assert len(a1) == 768
    assert math.isclose(sum(v * v for v in a1), 1.0, rel_tol=1e-9)


async def test_fake_embedder_similar_texts_are_closer():
    e = FakeEmbedder()
    query, related, unrelated = (
        e.embed_one("active transport uses ATP"),
        e.embed_one("active transport needs ATP energy"),
        e.embed_one("Mendelian inheritance of pea plants"),
    )

    def cos(a, b):  # vectors are normalised
        return sum(x * y for x, y in zip(a, b, strict=True))

    assert cos(query, related) > cos(query, unrelated)


async def test_fake_llm_fills_structured_output():
    llm = get_llm()
    mcq = await llm.generate_json("any prompt", GeneratedMCQ)
    assert isinstance(mcq, GeneratedMCQ)
    visual = await llm.generate_json("any prompt", VisualDecision)
    assert visual.kind == "diagram"


def test_providers_default_to_fakes_without_keys():
    assert get_llm().name == "fake-llm"  # type: ignore[attr-defined]
    assert get_embedder().name == "fake-embedder"  # type: ignore[attr-defined]


def test_all_prompt_templates_parse():
    env = Environment(loader=FileSystemLoader(PROMPTS_DIR))
    names = list_prompts()
    assert len(names) >= 9
    for name in names:
        assert ".v" in name, f"{name} must be versioned, e.g. name.v1.j2"
        env.parse(env.loader.get_source(env, name)[0])  # type: ignore[union-attr]


def test_render_prompt():
    prompt = render_prompt(
        "notes/generate_notes", 1, unit_title="Unit 2", topic_title="Osmosis", context="[1] ..."
    )
    assert "Topic: Osmosis" in prompt
    assert "{#" not in prompt
