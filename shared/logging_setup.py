"""Logging for both services.

    configure_logging(settings.LOG_LEVEL, settings.ENVIRONMENT)

* prod: one JSON object per line on stdout, with the fields Google Cloud Logging reads
  ("severity", "message", "time", "logger"); tracebacks go into "message" so Error Reporting
  groups them.
* dev / test: plain readable lines.
* Everywhere: email addresses are replaced by "[email]" before a line is written (messages,
  arguments and tracebacks), so a careless log call cannot leak them. Student answers and other
  free text must simply never be logged; the database engine hides query parameters in prod
  for the same reason (shared/db/session.py).

uvicorn's own loggers (startup lines, access log) are routed through the same handler.
"""

import json
import logging
import re
import sys
from datetime import UTC, datetime

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
REDACTED_EMAIL = "[email]"
UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


def redact(text: str) -> str:
    """Remove personal data we can recognise (email addresses) from one log text."""
    return EMAIL_RE.sub(REDACTED_EMAIL, text)


class RedactingFormatter(logging.Formatter):
    """Plain text lines with email addresses removed."""

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


class JsonFormatter(logging.Formatter):
    """One JSON object per line (Cloud Logging structured logs), email addresses removed."""

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        if record.exc_info:
            message = f"{message}\n{self.formatException(record.exc_info)}"
        elif record.exc_text:
            message = f"{message}\n{record.exc_text}"
        if record.stack_info:
            message = f"{message}\n{self.formatStack(record.stack_info)}"
        entry = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "severity": record.levelname,
            "logger": record.name,
            "message": redact(message),
        }
        return json.dumps(entry, ensure_ascii=False)


def configure_logging(level: str, environment: str) -> None:
    """Send every log line (ours and uvicorn's) to stdout in the format for `environment`."""
    handler = logging.StreamHandler(sys.stdout)
    if environment == "prod":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    for old in list(root.handlers):
        # Keep pytest's capture handlers; replace everything else (basicConfig, earlier calls).
        if type(old).__module__.startswith("_pytest"):
            continue
        root.removeHandler(old)
    root.addHandler(handler)
    root.setLevel(level)
    for name in UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True
