"""Write one `ai_usage_log` row per call to an AI provider (tokens, latency, estimated cost).

The admin Analytics screen reads these rows ("AI usage and cost"). Logging is best effort: a
database problem here is logged and swallowed, it never fails the AI call.
"""

import logging

from shared.db.models import AIUsageLog
from shared.db.session import SessionLocal

logger = logging.getLogger(__name__)

# US dollars per 1 million tokens: (input, output). Estimates for the cost column only; the
# free tier is billed at 0. Unknown models are logged without a cost rather than a guess.
PRICES_PER_MILLION: dict[str, tuple[float, float]] = {}


def estimate_cost(
    model: str | None, input_tokens: int | None, output_tokens: int | None
) -> float | None:
    """Pure: the cost of one call, or None when the model's price is not configured."""
    price = PRICES_PER_MILLION.get(model or "")
    if price is None:
        return None
    return round(((input_tokens or 0) * price[0] + (output_tokens or 0) * price[1]) / 1_000_000, 6)


async def record_usage(
    *,
    provider: str,
    operation: str,
    model: str | None = None,
    prompt_name: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    images: int = 0,
    latency_ms: int | None = None,
    success: bool = True,
) -> None:
    try:
        async with SessionLocal() as session:
            session.add(
                AIUsageLog(
                    provider=provider,
                    model=model,
                    operation=operation,
                    prompt_name=(prompt_name or None) and str(prompt_name)[:100],
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    images=images,
                    latency_ms=latency_ms,
                    cost_usd=estimate_cost(model, input_tokens, output_tokens),
                    success=success,
                )
            )
            await session.commit()
    except Exception:
        logger.warning("Could not write the AI usage log", exc_info=True)
