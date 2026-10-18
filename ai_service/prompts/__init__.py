"""Versioned Jinja2 prompt templates.

Files are named  <pipeline>/<prompt_name>.v<N>.j2 , e.g. notes/generate_notes.v1.j2

    from ai_service.prompts import render_prompt
    prompt = render_prompt("notes/generate_notes", version=1, topic_title="...", context="...")

Never edit a prompt that is already used in production: copy it to .v2.j2, change the copy,
and bump the version in the pipeline. Store `prompt_id("notes/generate_notes", 1)` with the
generated content so we always know which prompt produced it.
"""

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

PROMPTS_DIR = Path(__file__).parent

# StrictUndefined: a missing variable is an error, not a silent empty string.
_env = Environment(
    loader=FileSystemLoader(PROMPTS_DIR),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=False,
    autoescape=False,  # prompts are plain text, not HTML
)


def prompt_id(name: str, version: int) -> str:
    return f"{name}.v{version}"


def render_prompt(name: str, version: int = 1, **variables: Any) -> str:
    template = _env.get_template(f"{prompt_id(name, version)}.j2")
    return template.render(**variables).strip()


def list_prompts() -> list[str]:
    """All template files, e.g. ["notes/generate_notes.v1.j2", ...]."""
    return sorted(p.relative_to(PROMPTS_DIR).as_posix() for p in PROMPTS_DIR.rglob("*.j2"))
