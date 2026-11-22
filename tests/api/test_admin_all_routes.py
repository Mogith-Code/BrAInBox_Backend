"""EVERY /api/v1/admin route refuses students (403) and anonymous callers (401).

The routes come from the live OpenAPI schema, so a new admin route is checked automatically.
Path parameters get a well-formed dummy value, so the role check (not a 404/422) is what
answers. No database is needed: the role check runs before the route touches it.
"""

import re
import uuid

import pytest

from api.main import create_app

ADMIN_PREFIX = "/api/v1/admin"
DUMMY_ID = str(uuid.UUID(int=99))


def _dummy(schema: dict) -> str:
    if schema.get("type") == "integer":
        return "1"
    if schema.get("format") == "uuid":
        return DUMMY_ID
    if "enum" in schema:
        return str(schema["enum"][0])
    return DUMMY_ID  # a plain string id


def admin_operations() -> list[tuple[str, str]]:
    """(METHOD, concrete path) for every operation under /api/v1/admin."""
    schema = create_app().openapi()
    operations = []
    for path, ops in schema["paths"].items():
        if not path.startswith(ADMIN_PREFIX):
            continue
        for method, op in ops.items():
            params = {
                p["name"]: _dummy(p.get("schema", {}))
                for p in op.get("parameters", [])
                if p.get("in") == "path"
            }
            concrete = re.sub(
                r"\{(\w+)\}", lambda m, params=params: params.get(m[1], DUMMY_ID), path
            )
            operations.append((method.upper(), concrete))
    return operations


OPERATIONS = admin_operations()


def test_admin_routes_were_found():
    # Guard against the walk silently finding nothing (e.g. a renamed prefix).
    assert len(OPERATIONS) >= 40
    assert {method for method, _ in OPERATIONS} >= {"GET", "POST", "PATCH", "DELETE"}


@pytest.mark.parametrize(("method", "path"), OPERATIONS)
async def test_every_admin_route_is_forbidden_for_students(client, method, path):
    response = await client.request(method, path, json={})
    assert response.status_code == 403, f"{method} {path} -> {response.status_code}"
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.parametrize(("method", "path"), OPERATIONS)
async def test_every_admin_route_needs_a_login(anon_client, method, path):
    response = await anon_client.request(method, path, json={})
    assert response.status_code == 401, f"{method} {path} -> {response.status_code}"
