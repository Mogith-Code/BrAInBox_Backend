"""Tests for the community module: study groups. Owner: Mogith."""

import asyncio
import random
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import delete

from api.modules.community import repository
from shared.db.models import CommunityGroup, GroupMember, Unit, User
from shared.enums import UserRole
from tests.conftest import STUDENT

# --------------------------------------------------------------------------- placeholders


async def test_community_status_requires_login(anon_client):
    response = await anon_client.get("/api/v1/community/status")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_community_status_placeholder(client):
    response = await client.get("/api/v1/community/status")
    assert response.status_code == 200
    assert response.json() == {"module": "community", "status": "todo"}


# --------------------------------------------------------------------------- groups (no DB)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/groups"),
        ("get", "/api/v1/groups/general"),
        ("post", "/api/v1/groups/general/join"),
        ("delete", "/api/v1/groups/general/join"),
    ],
)
async def test_groups_require_login(anon_client, method, path):
    assert (await anon_client.request(method, path)).status_code == 401


async def test_unknown_group_is_not_found(client, monkeypatch):
    async def nothing(session, ref, user_id):
        return None

    monkeypatch.setattr(repository, "get_group", nothing)
    for method, path in [
        ("get", f"/api/v1/groups/{uuid.uuid4()}"),
        ("post", "/api/v1/groups/no-such-group/join"),
        ("delete", "/api/v1/groups/no-such-group/join"),
    ]:
        response = await client.request(method, path)
        assert response.status_code == 404, path
        assert response.json()["error"]["code"] == "GROUP_NOT_FOUND"


# --------------------------------------------------------------------------- groups (DB)


@pytest.fixture
async def groups(db_session, student_in_db):
    """A public group and a private one (with another student as its only member)."""
    tag = uuid.uuid4().hex[:8]
    other = User(firebase_uid=f"community-{tag}", role=UserRole.STUDENT)
    public = CommunityGroup(name=f"Public {tag}", slug=f"test-public-{tag}")
    private = CommunityGroup(
        name=f"Private {tag}", slug=f"test-private-{tag}", is_private=True, member_count=1
    )
    db_session.add_all([other, public, private])
    await db_session.flush()
    db_session.add(GroupMember(group_id=private.id, user_id=other.id, role="owner"))
    await db_session.commit()
    yield SimpleNamespace(public=public, private=private)
    await db_session.execute(
        delete(CommunityGroup).where(CommunityGroup.id.in_([public.id, private.id]))
    )
    await db_session.execute(delete(User).where(User.id == other.id))
    await db_session.commit()


@pytest.mark.db
async def test_list_groups_hides_private_groups_from_non_members(client, groups):
    body = (await client.get("/api/v1/groups")).json()
    ids = [g["id"] for g in body]
    assert str(groups.public.id) in ids
    assert str(groups.private.id) not in ids
    mine = next(g for g in body if g["id"] == str(groups.public.id))
    assert (mine["is_member"], mine["my_role"], mine["member_count"]) == (False, None, 0)
    defaults = [g["is_default"] for g in body]
    assert defaults == sorted(defaults, reverse=True)  # the default group(s) come first


@pytest.mark.db
async def test_get_group_by_uuid_or_slug(client, groups):
    by_id = await client.get(f"/api/v1/groups/{groups.public.id}")
    by_slug = await client.get(f"/api/v1/groups/{groups.public.slug}")
    assert by_id.status_code == by_slug.status_code == 200
    assert by_id.json() == by_slug.json()


@pytest.mark.db
async def test_private_group_is_not_found_for_non_members(client, groups):
    for method, suffix in [("get", ""), ("post", "/join"), ("delete", "/join")]:
        response = await client.request(method, f"/api/v1/groups/{groups.private.id}{suffix}")
        assert response.status_code == 404, suffix
        assert response.json()["error"]["code"] == "GROUP_NOT_FOUND"


@pytest.mark.db
async def test_private_group_is_visible_to_its_members(client, groups, db_session):
    db_session.add(GroupMember(group_id=groups.private.id, user_id=STUDENT.id, role="member"))
    await db_session.commit()
    assert str(groups.private.id) in [g["id"] for g in (await client.get("/api/v1/groups")).json()]
    mine = (await client.get(f"/api/v1/groups/{groups.private.slug}")).json()
    assert (mine["is_member"], mine["my_role"]) == (True, "member")


@pytest.mark.db
async def test_join_and_leave_keep_the_member_count_right(client, groups):
    path = f"/api/v1/groups/{groups.public.slug}/join"

    joined = (await client.post(path)).json()
    assert (joined["is_member"], joined["my_role"], joined["member_count"]) == (True, "member", 1)
    again = (await client.post(path)).json()
    assert again["member_count"] == 1  # joining twice changes nothing

    left = (await client.delete(path)).json()
    assert (left["is_member"], left["my_role"], left["member_count"]) == (False, None, 0)
    again = (await client.delete(path)).json()
    assert again["member_count"] == 0  # leaving twice changes nothing (never below 0)


@pytest.mark.db
async def test_unit_groups_are_ordered_by_unit_number(client, db_session, student_in_db):
    """Unit 2 before Unit 10 (sorting by the slug text would put "unit-10" first)."""
    tag = uuid.uuid4().hex[:8]
    base = random.randint(100_000, 899_000)
    unit2 = Unit(number=base + 2, title="Order test 2")
    unit10 = Unit(number=base + 10, title="Order test 10")
    db_session.add_all([unit2, unit10])
    await db_session.flush()
    later = CommunityGroup(name=f"A {tag}", slug=f"order-{tag}-10", unit_id=unit10.id)
    earlier = CommunityGroup(name=f"B {tag}", slug=f"order-{tag}-2", unit_id=unit2.id)
    db_session.add_all([later, earlier])
    await db_session.commit()
    try:
        ids = [g["id"] for g in (await client.get("/api/v1/groups")).json()]
        assert ids.index(str(earlier.id)) < ids.index(str(later.id))
    finally:
        await db_session.execute(
            delete(CommunityGroup).where(CommunityGroup.id.in_([later.id, earlier.id]))
        )
        await db_session.execute(delete(Unit).where(Unit.id.in_([unit2.id, unit10.id])))
        await db_session.commit()


@pytest.mark.db
async def test_two_joins_at_the_same_moment_count_once(client, groups):
    path = f"/api/v1/groups/{groups.public.slug}/join"
    first, second = await asyncio.gather(client.post(path), client.post(path))
    assert first.status_code == second.status_code == 200
    final = (await client.get(f"/api/v1/groups/{groups.public.slug}")).json()
    assert final["member_count"] == 1
