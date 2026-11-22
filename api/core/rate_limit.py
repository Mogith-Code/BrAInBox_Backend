"""Per-minute request limits for the routes attackers or runaway clients would hammer.

* auth: the sign-up / email-code / password-reset routes, counted per client IP
  (RATE_LIMIT_AUTH_PER_MINUTE). Slows down guessing 6-digit codes and email flooding.
* ai: the routes that start AI work (they cost money per call), counted per login token, or per
  IP without one (RATE_LIMIT_AI_PER_MINUTE). The daily per-student caps (EVALUATIONS_DAILY_LIMIT,
  PAPERS_DAILY_LIMIT...) still apply on top; this only stops bursts.

Too many requests -> 429 {"error": {"code": "RATE_LIMITED", "retry_after": N}} + Retry-After.

Counts are kept in memory, per API instance (Cloud Run runs at most 2), so the real limit is at
most instances x the setting. That is enough to stop abuse without a shared store.

A NEW route that starts AI work must be added to AI_ROUTES below.
"""

import hashlib
import re
import time
from collections import deque
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from api.core.config import get_settings
from api.core.errors import error_body, shaped_body

WINDOW_SECONDS = 60.0
# Forget idle clients once this many are tracked, so memory stays small.
MAX_TRACKED_KEYS = 10_000

_ID = r"[^/]+"
# (method, path regex) -> bucket. Paths are full paths, including /api/v1.
AUTH_ROUTES = [
    ("POST", r"/api/v1/auth/register"),
    ("POST", r"/api/v1/auth/email-code/(send|verify)"),
    ("POST", r"/api/v1/auth/password-reset/(send|verify|complete)"),
]
AI_ROUTES = [
    ("POST", rf"/api/v1/learn/topics/{_ID}/notes/generate"),
    ("POST", r"/api/v1/learn/ask"),
    ("POST", r"/api/v1/learn/uploads"),
    ("POST", r"/api/v1/uploads/(text|pdf)"),
    ("POST", r"/api/v1/visuals/generate"),
    ("POST", rf"/api/v1/questions/{_ID}/explain"),
    ("POST", r"/api/v1/papers/(generate|generate-by-units)"),
    ("POST", rf"/api/v1/papers/{_ID}/submit"),
    ("POST", r"/api/v1/evaluations(/ocr)?"),
    ("POST", r"/api/v1/study-plan/regenerate"),
    ("POST", r"/api/v1/posts/suggest-topic"),
    ("POST", rf"/api/v1/groups/{_ID}/posts"),
    ("POST", rf"/api/v1/diagnostic/{_ID}/submit"),
    # Old exam app URLs (api/modules/exams/router.py legacy_router)
    ("POST", r"/exam/(generate-paper|generate-paper-by-units|evaluate)"),
]


def _compile(routes: list[tuple[str, str]]) -> list[tuple[str, re.Pattern[str]]]:
    return [(method, re.compile(f"^{pattern}/?$")) for method, pattern in routes]


_BUCKETS = {"auth": _compile(AUTH_ROUTES), "ai": _compile(AI_ROUTES)}


def bucket_for(method: str, path: str) -> str | None:
    """ "auth", "ai" or None (not limited) for one request."""
    for bucket, routes in _BUCKETS.items():
        if any(m == method and pattern.match(path) for m, pattern in routes):
            return bucket
    return None


def client_ip(request: Request, proxy_hops: int) -> str:
    """The caller's IP. Behind `proxy_hops` proxies that each append to X-Forwarded-For, the
    client is that many entries from the right (entries further left are set by the client and
    could be faked)."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if proxy_hops > 0 and forwarded:
        hops = [h.strip() for h in forwarded.split(",") if h.strip()]
        if hops:
            return hops[-min(proxy_hops, len(hops))]
    return request.client.host if request.client else "unknown"


class RateLimiter:
    """Sliding one-minute window per key, in memory."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}

    def hit(self, key: str, limit: int) -> int:
        """Count one request. 0 = allowed, otherwise seconds to wait."""
        now = self._clock()
        hits = self._hits.get(key)
        if hits is None:
            if len(self._hits) >= MAX_TRACKED_KEYS:
                self._forget_idle(now)
            hits = self._hits[key] = deque()
        while hits and hits[0] <= now - WINDOW_SECONDS:
            hits.popleft()
        if len(hits) >= limit:
            return max(1, int(hits[0] + WINDOW_SECONDS - now + 0.999))
        hits.append(now)
        return 0

    def _forget_idle(self, now: float) -> None:
        idle = [k for k, h in self._hits.items() if not h or h[-1] <= now - WINDOW_SECONDS]
        for key in idle:
            del self._hits[key]
        if len(self._hits) >= MAX_TRACKED_KEYS:  # everyone is active: start again
            self._hits.clear()


def _key(bucket: str, request: Request, proxy_hops: int) -> str:
    auth = request.headers.get("authorization", "")
    if bucket == "ai" and auth:
        # Per login. Only a hash is kept, never the token itself.
        return "ai:" + hashlib.sha256(auth.encode()).hexdigest()
    return f"{bucket}:{client_ip(request, proxy_hops)}"


def rate_limit_middleware(
    limiter: RateLimiter,
) -> Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]:
    """HTTP middleware for app.middleware("http"). Settings are read on every request."""

    async def middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        bucket = bucket_for(request.method, request.url.path)
        if bucket is not None:
            settings = get_settings()
            limit = (
                settings.RATE_LIMIT_AUTH_PER_MINUTE
                if bucket == "auth"
                else settings.RATE_LIMIT_AI_PER_MINUTE
            )
            if limit > 0:
                key = _key(bucket, request, settings.RATE_LIMIT_PROXY_HOPS)
                retry_after = limiter.hit(key, limit)
                if retry_after:
                    body = error_body("RATE_LIMITED", "Too many requests. Try again shortly.")
                    body["error"]["retry_after"] = retry_after
                    return JSONResponse(
                        status_code=429,
                        content=shaped_body(request, body),
                        headers={"Retry-After": str(retry_after)},
                    )
        return await call_next(request)

    return middleware
