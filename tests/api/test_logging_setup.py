"""Production logs are JSON lines and never contain email addresses."""

import json
import logging

from shared.db.session import make_engine
from shared.logging_setup import JsonFormatter, RedactingFormatter, redact


def _record(msg: str, *args: object, exc: bool = False) -> logging.LogRecord:
    exc_info = None
    if exc:
        try:
            raise ValueError("bad value for student@example.com")
        except ValueError:
            import sys

            exc_info = sys.exc_info()
    return logging.LogRecord("api.test", logging.ERROR, __file__, 1, msg, args, exc_info)


def test_redact_removes_email_addresses():
    assert redact("to=Kamal.Perera+1@mail.school.lk ok") == "to=[email] ok"
    assert redact("no personal data here") == "no personal data here"


def test_json_formatter_gives_one_cloud_logging_line():
    line = JsonFormatter().format(_record("Email sent to %s", "a.b@example.com", exc=True))
    entry = json.loads(line)
    assert "\n" not in line
    assert entry["severity"] == "ERROR"
    assert entry["logger"] == "api.test"
    assert entry["message"].startswith("Email sent to [email]")
    assert "ValueError" in entry["message"]  # the traceback is kept...
    assert "@example.com" not in line  # ...without the email in its message


def test_plain_formatter_also_redacts():
    text = RedactingFormatter("%(message)s").format(_record("user %s", "x@y.org"))
    assert text == "user [email]"


def test_production_engine_hides_query_parameters(monkeypatch):
    from shared.settings import get_shared_settings

    monkeypatch.setattr(get_shared_settings(), "ENVIRONMENT", "prod")
    engine = make_engine("postgresql+asyncpg://u:p@localhost/db")
    assert engine.sync_engine.hide_parameters is True
