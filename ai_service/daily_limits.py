"""Daily caps that keep every AI provider inside its FREE allowance.

Every real provider call first calls `use_quota(...)`. It counts today's calls in the
`ai_usage_log` table and, if the cap is not reached yet, saves one more row (BEFORE the call,
so retries and failed calls count too: we would rather stop early than pay).

    await use_quota("cloudflare", "image", model, settings.IMAGE_DAILY_LIMIT, images=1)

A cap of 0 means "no cap" (use it only with a paid account). The fakes never count.

"Today" follows each provider's own reset time:
  * Cloudflare Workers AI: 00:00 UTC
  * Google (Gemini, Vision): midnight Pacific time. We use UTC-8 all year: in summer (UTC-7)
    our day starts one hour after Google's, which only makes us stop a little earlier.

The free numbers (and where to check them) are in ai_service/pipelines/visuals/README.md.
"""

import logging
from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ai_service.errors import UserInputError
from shared.db.models import AIUsageLog
from shared.db.session import SessionLocal

logger = logging.getLogger(__name__)

PACIFIC_STANDARD = timezone(timedelta(hours=-8), name="PST")
RESET_ZONES = {"gemini": PACIFIC_STANDARD, "vision": PACIFIC_STANDARD, "cloudflare": UTC}


class DailyLimitReached(UserInputError):
    """Today's free allowance of a provider is used up. The message is safe to show."""

    code = "AI_DAILY_LIMIT"


def day_start(provider: str, now: datetime | None = None) -> datetime:
    """When the provider's current "day" started (timezone-aware)."""
    zone = RESET_ZONES.get(provider, UTC)
    local = (now or datetime.now(UTC)).astimezone(zone)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def limit_message(operation: str) -> str:
    what = "pictures" if operation == "image" else "AI requests"
    return f"Today's free {what} are used up. Please try again tomorrow."


async def used_today(provider: str, operation: str) -> int:
    """How many calls were counted today (0 if the database can't be read)."""
    try:
        async with SessionLocal() as session:
            return await _count(session, provider, operation)
    except Exception:
        logger.warning("Could not read today's %s %s usage", provider, operation)
        return 0


async def _count(session: AsyncSession, provider: str, operation: str) -> int:
    result = await session.execute(
        select(func.count()).where(
            AIUsageLog.provider == provider,
            AIUsageLog.operation == operation,
            AIUsageLog.created_at >= day_start(provider),
        )
    )
    return int(result.scalar_one())


async def has_quota(provider: str, operation: str, limit: int) -> bool:
    """True if at least one more call fits today (always True without a cap)."""
    return limit <= 0 or await used_today(provider, operation) < limit


async def use_quota(
    provider: str,
    operation: str,
    model: str | None,
    limit: int,
    *,
    prompt_name: str | None = None,
    images: int = 0,
) -> None:
    """Count one call, or raise DailyLimitReached when today's cap is reached.

    If the database is down we log it and let the call through (the provider's own free-tier
    limit still stops it: without billing, Google and Cloudflare answer 429 instead of charging).
    """
    if limit <= 0:
        return
    try:
        async with SessionLocal() as session:
            # One counter at a time per provider/operation, so two jobs can't both take the
            # last free call. The lock ends with the transaction (commit / rollback).
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                {"key": f"daily_limit:{provider}:{operation}"},
            )
            if await _count(session, provider, operation) >= limit:
                raise DailyLimitReached(limit_message(operation))
            session.add(
                AIUsageLog(
                    provider=provider,
                    model=model,
                    operation=operation,
                    prompt_name=prompt_name,
                    images=images,
                )
            )
            await session.commit()
    except DailyLimitReached:
        logger.warning("Daily %s %s limit (%s) reached", provider, operation, limit)
        raise
    except Exception:
        logger.exception("Could not count %s %s usage; allowing the call", provider, operation)
