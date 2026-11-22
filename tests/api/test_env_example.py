""".env.example lists every setting, each with a one-line comment, and no real secrets."""

import re
from pathlib import Path

from ai_service.config import AISettings
from api.core.config import ApiSettings

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"
LINE_RE = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")


def _variables() -> dict[str, tuple[str, str]]:
    """name -> (value, the comment line just above it)."""
    lines = ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
    found = {}
    for i, line in enumerate(lines):
        match = LINE_RE.match(line)
        if match:
            found[match[1]] = (match[2], lines[i - 1] if i else "")
    return found


def test_every_setting_is_in_env_example():
    names = set(ApiSettings.model_fields) | set(AISettings.model_fields)
    missing = sorted(names - set(_variables()))
    assert not missing, f"add to .env.example: {missing}"


def test_every_variable_has_a_one_line_comment():
    uncommented = [n for n, (_, above) in _variables().items() if not above.startswith("# ")]
    assert not uncommented


def test_no_real_secrets():
    secret_suffixes = ("_KEY", "_TOKEN", "_SECRET", "_PASSWORD")
    allowed = {"dev-service-token", "dev-only-change-me", "brainbox", ""}
    for name, (value, _) in _variables().items():
        if name.endswith(secret_suffixes):
            assert value in allowed, f"{name} must not hold a real value"
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    # The key header is split so the pre-commit "detect-private-key" hook does not flag this file.
    private_key_header = "BEGIN " + "PRIVATE KEY"
    assert not re.search(r"AIza[0-9A-Za-z_-]{20,}", text)
    assert private_key_header not in text
