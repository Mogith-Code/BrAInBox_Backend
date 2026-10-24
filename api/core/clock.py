"""Time helpers. All students are in Sri Lanka, so "today" means Sri Lanka's date.

Sri Lanka is UTC+05:30 all year (no daylight saving), so a fixed offset is enough and
works on Windows without extra time-zone data. Tests can monkeypatch `now()`.
"""

from datetime import UTC, date, datetime, timedelta, timezone

SRI_LANKA = timezone(timedelta(hours=5, minutes=30), name="Asia/Colombo")


def now() -> datetime:
    """Current time (timezone-aware, UTC). Use this instead of datetime.now() in services."""
    return datetime.now(UTC)


def today() -> date:
    """The student's local date (Sri Lanka)."""
    return now().astimezone(SRI_LANKA).date()
