"""Per-minute limits on the auth and AI routes (api/core/rate_limit.py)."""

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request

from api.core.config import get_settings
from api.core.rate_limit import RateLimiter, bucket_for, client_ip
from api.main import create_app


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_limiter_allows_up_to_the_limit_then_waits_for_the_window():
    clock = Clock()
    limiter = RateLimiter(clock)
    assert [limiter.hit("k", 3) for _ in range(3)] == [0, 0, 0]
    assert limiter.hit("k", 3) == 60  # the oldest hit leaves the window in 60 s
    clock.now += 30
    assert 29 <= limiter.hit("k", 3) <= 31
    assert limiter.hit("other", 3) == 0  # keys are separate
    clock.now += 31
    assert limiter.hit("k", 3) == 0  # the window moved on


@pytest.mark.parametrize(
    ("method", "path", "bucket"),
    [
        ("POST", "/api/v1/auth/email-code/verify", "auth"),
        ("POST", "/api/v1/auth/password-reset/send", "auth"),
        ("POST", "/api/v1/auth/register", "auth"),
        ("GET", "/api/v1/auth/me", None),
        ("POST", "/api/v1/evaluations", "ai"),
        ("POST", "/api/v1/evaluations/ocr", "ai"),
        ("POST", "/api/v1/evaluations/pages", None),
        ("POST", "/api/v1/papers/generate", "ai"),
        ("POST", "/api/v1/learn/topics/abc/notes/generate", "ai"),
        ("POST", "/api/v1/visuals/generate", "ai"),
        ("POST", "/exam/generate-paper", "ai"),
        ("GET", "/api/v1/papers/generate", None),
        ("POST", "/api/v1/quizzes", None),
    ],
)
def test_bucket_for(method, path, bucket):
    assert bucket_for(method, path) == bucket


def test_every_limited_pattern_matches_a_real_route():
    """A typo in AUTH_ROUTES / AI_ROUTES would silently leave a route unlimited."""
    import re

    from api.core.rate_limit import _BUCKETS
    from api.modules.exams.router import legacy_router

    paths = set(create_app().openapi()["paths"]) | {r.path for r in legacy_router.routes}
    concrete = {re.sub(r"\{\w+\}", "x", p) for p in paths}
    for routes in _BUCKETS.values():
        for _, pattern in routes:
            assert any(pattern.match(p) for p in concrete), pattern.pattern


def _request(forwarded: str | None, peer: str = "10.0.0.1") -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request({"type": "http", "headers": headers, "client": (peer, 1234)})


def test_client_ip_uses_the_entry_the_trusted_proxy_added():
    # The client can send its own X-Forwarded-For; Cloud Run appends the real address last.
    request = _request("6.6.6.6, 203.0.113.9")
    assert client_ip(request, proxy_hops=1) == "203.0.113.9"
    assert client_ip(request, proxy_hops=2) == "6.6.6.6"
    assert client_ip(request, proxy_hops=0) == "10.0.0.1"
    assert client_ip(_request(None), proxy_hops=1) == "10.0.0.1"


@pytest.fixture
def limits(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "RATE_LIMIT_AUTH_PER_MINUTE", 2)
    monkeypatch.setattr(settings, "RATE_LIMIT_AI_PER_MINUTE", 2)
    monkeypatch.setattr(settings, "RATE_LIMIT_PROXY_HOPS", 1)


async def test_auth_route_returns_429_with_retry_after(limits):
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as c:
        ip = {"X-Forwarded-For": "198.51.100.7"}
        statuses = [
            (await c.post("/api/v1/auth/password-reset/send", json={}, headers=ip)).status_code
            for _ in range(2)
        ]
        assert 429 not in statuses
        blocked = await c.post("/api/v1/auth/password-reset/send", json={}, headers=ip)
        assert blocked.status_code == 429
        assert blocked.json()["error"]["code"] == "RATE_LIMITED"
        assert int(blocked.headers["Retry-After"]) >= 1
        # Another client is not affected.
        other = await c.post(
            "/api/v1/auth/password-reset/send", json={}, headers={"X-Forwarded-For": "192.0.2.1"}
        )
        assert other.status_code != 429


async def test_ai_route_is_limited_per_login_token(limits):
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as c:
        a = {"Authorization": "Bearer token-a"}
        for _ in range(2):
            assert (await c.post("/api/v1/visuals/generate", json={}, headers=a)).status_code != 429
        assert (await c.post("/api/v1/visuals/generate", json={}, headers=a)).status_code == 429
        b = {"Authorization": "Bearer token-b"}
        assert (await c.post("/api/v1/visuals/generate", json={}, headers=b)).status_code != 429


async def test_learn_route_429_has_the_learn_error_shape(limits):
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as c:
        path = "/api/v1/learn/topics/x/notes/generate"
        for _ in range(2):
            await c.post(path, headers={"Authorization": "Bearer t"})
        body = (await c.post(path, headers={"Authorization": "Bearer t"})).json()
        assert body["code"] == "RATE_LIMITED" and body["error"]["code"] == "RATE_LIMITED"


async def test_429_keeps_the_cors_headers_for_the_admin_portal(limits, monkeypatch):
    monkeypatch.setattr(get_settings(), "CORS_ORIGINS", "https://admin.example.org")
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as c:
        headers = {"Origin": "https://admin.example.org", "Authorization": "Bearer t"}
        for _ in range(2):
            await c.post("/api/v1/visuals/generate", json={}, headers=headers)
        blocked = await c.post("/api/v1/visuals/generate", json={}, headers=headers)
        assert blocked.status_code == 429
        assert blocked.headers["access-control-allow-origin"] == "https://admin.example.org"


async def test_limit_zero_turns_it_off(monkeypatch):
    monkeypatch.setattr(get_settings(), "RATE_LIMIT_AUTH_PER_MINUTE", 0)
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as c:
        for _ in range(5):
            r = await c.post("/api/v1/auth/password-reset/send", json={})
            assert r.status_code != 429
