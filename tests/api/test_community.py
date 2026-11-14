"""Tests for the community module: study groups and posts. Owner: Mogith."""

import asyncio
import random
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import delete

from api.core.security import CurrentUser, get_current_user
from api.main import create_app
from api.modules.community import repository
from shared.db.models import CommunityGroup, GroupMember, Post, Reply, Topic, Unit, User
from shared.enums import ModerationStatus, UserRole
from tests.conftest import STUDENT, _client

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


# --------------------------------------------------------------------------- posts (no DB)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/groups/general/posts"),
        ("post", "/api/v1/groups/general/posts"),
        ("get", f"/api/v1/posts/{uuid.uuid4()}"),
        ("patch", f"/api/v1/posts/{uuid.uuid4()}"),
        ("delete", f"/api/v1/posts/{uuid.uuid4()}"),
    ],
)
async def test_posts_require_login(anon_client, method, path):
    assert (await anon_client.request(method, path, json={})).status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        {"title": "Hi", "body": "Too short a title"},
        {"title": "A fine title", "body": ""},
        {"title": "A fine title", "body": "x", "tags": ["a", "b", "c", "d", "e", "f"]},
        {"title": "A fine title", "body": "x", "tags": ["x" * 51]},
    ],
)
async def test_create_post_validation(client, body):
    response = await client.post("/api/v1/groups/general/posts", json=body)
    assert response.status_code == 422


# --------------------------------------------------------------------------- posts (DB)

OTHER = CurrentUser(
    id=uuid.UUID(int=77), firebase_uid="community-other", email="other@test.local",
    role=UserRole.STUDENT,
)  # fmt: skip


def _client_as(user: CurrentUser):  # type: ignore[no-untyped-def]
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: user
    return _client(app)


@pytest.fixture
async def forum(db_session, student_in_db):
    """A unit group (the test student and OTHER are members) with a topic in its unit, a topic
    in another unit, and a private group. Everything is removed afterwards."""
    tag = uuid.uuid4().hex[:8]
    base = random.randint(100_000, 899_000)
    other = User(
        id=OTHER.id, firebase_uid=OTHER.firebase_uid, display_name="Kasun", role=UserRole.STUDENT
    )
    unit, far_unit = Unit(number=base, title="Forum unit"), Unit(number=base + 1, title="Far unit")
    db_session.add_all([other, unit, far_unit])
    await db_session.flush()
    topic = Topic(unit_id=unit.id, number="F.1", title="Forum topic")
    far_topic = Topic(unit_id=far_unit.id, number="G.1", title="Far topic")
    group = CommunityGroup(
        name=f"Forum {tag}", slug=f"forum-{tag}", unit_id=unit.id, member_count=2
    )
    private = CommunityGroup(name=f"Secret {tag}", slug=f"secret-{tag}", is_private=True)
    db_session.add_all([topic, far_topic, group, private])
    await db_session.flush()
    db_session.add_all(
        [
            GroupMember(group_id=group.id, user_id=STUDENT.id),
            GroupMember(group_id=group.id, user_id=OTHER.id),
            GroupMember(group_id=private.id, user_id=OTHER.id),
        ]
    )
    await db_session.commit()
    yield SimpleNamespace(group=group, private=private, topic=topic, far_topic=far_topic, unit=unit)
    await db_session.execute(
        delete(CommunityGroup).where(CommunityGroup.id.in_([group.id, private.id]))
    )
    await db_session.execute(delete(User).where(User.id == OTHER.id))
    await db_session.execute(delete(Unit).where(Unit.id.in_([unit.id, far_unit.id])))
    await db_session.commit()


async def _post(db_session, group, author_id, title, **extra):  # type: ignore[no-untyped-def]
    """A post saved straight in the database. Approved unless a test says otherwise (the
    model's own default is pending)."""
    extra.setdefault("moderation_status", ModerationStatus.APPROVED)
    post = Post(group_id=group.id, author_id=author_id, title=title, body="body", **extra)
    db_session.add(post)
    await db_session.commit()
    return post


@pytest.mark.db
async def test_only_members_can_post(client, forum, db_session):
    body = {"title": "How does linkage work?", "body": "Please explain."}
    general = CommunityGroup(name="Not joined", slug=f"not-joined-{uuid.uuid4().hex[:8]}")
    db_session.add(general)
    await db_session.commit()
    try:
        response = await client.post(f"/api/v1/groups/{general.slug}/posts", json=body)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "NOT_A_MEMBER"
    finally:
        await db_session.execute(delete(CommunityGroup).where(CommunityGroup.id == general.id))
        await db_session.commit()


@pytest.mark.db
async def test_create_post_is_published_straight_away(client, forum):
    response = await client.post(
        f"/api/v1/groups/{forum.group.slug}/posts",
        json={
            "title": "  How does linkage work?  ",
            "body": "Please explain.",
            "topic_id": str(forum.topic.id),
            "tags": [" Genetics", "genetics", "LINKAGE"],
        },
    )
    assert response.status_code == 201, response.text
    post = response.json()
    assert post["title"] == "How does linkage work?"
    assert post["tags"] == ["genetics", "linkage"]  # cleaned: trimmed, lower-case, no duplicates
    assert (post["topic"], post["unit_id"]) == ("Forum topic", str(forum.unit.id))
    assert post["moderation_status"] == "approved"  # option A: no review queue yet
    assert (post["is_mine"], post["author"]["name"]) == (True, "Nethmi Perera")
    assert (post["score"], post["reply_count"], post["accepted_reply_id"]) == (0, 0, None)


@pytest.mark.db
async def test_topic_must_belong_to_the_groups_unit(client, forum):
    wrong = await client.post(
        f"/api/v1/groups/{forum.group.slug}/posts",
        json={"title": "Wrong unit", "body": "x", "topic_id": str(forum.far_topic.id)},
    )
    assert wrong.status_code == 400
    assert wrong.json()["error"]["code"] == "TOPIC_NOT_IN_GROUP_UNIT"
    unknown = await client.post(
        f"/api/v1/groups/{forum.group.slug}/posts",
        json={"title": "Unknown topic", "body": "x", "topic_id": str(uuid.uuid4())},
    )
    assert unknown.json()["error"]["code"] == "TOPIC_NOT_FOUND"


@pytest.mark.db
async def test_feed_sorting_and_paging(client, forum, db_session):
    old = await _post(db_session, forum.group, OTHER.id, "Old but popular", score=9)
    await _post(db_session, forum.group, OTHER.id, "Newer", score=1)
    newest = await _post(db_session, forum.group, STUDENT.id, "Newest", score=0)
    base = f"/api/v1/groups/{forum.group.slug}/posts"

    new = (await client.get(base)).json()
    assert [p["title"] for p in new["items"]] == ["Newest", "Newer", "Old but popular"]
    top = (await client.get(f"{base}?sort=top")).json()
    assert top["items"][0]["id"] == str(old.id)

    page = (await client.get(f"{base}?size=2&page=2")).json()
    assert (page["total"], page["pages"], len(page["items"])) == (3, 2, 1)
    assert (await client.get(f"{base}?sort=random")).status_code == 422
    assert new["items"][0]["id"] == str(newest.id) and new["items"][0]["is_mine"] is True


@pytest.mark.db
async def test_who_sees_which_posts(client, forum, db_session):
    await _post(db_session, forum.group, OTHER.id, "Approved")
    await _post(db_session, forum.group, OTHER.id, "Their pending", moderation_status="pending")
    await _post(db_session, forum.group, STUDENT.id, "My flagged", moderation_status="flagged")
    await _post(db_session, forum.group, OTHER.id, "Removed", moderation_status="removed")
    deleted = await _post(db_session, forum.group, STUDENT.id, "Deleted")
    deleted.deleted_at = deleted.created_at
    await db_session.commit()

    titles = {
        p["title"]
        for p in (await client.get(f"/api/v1/groups/{forum.group.slug}/posts")).json()["items"]
    }
    assert titles == {"Approved", "My flagged"}  # only my own flagged post, never others'

    secret = await _post(db_session, forum.private, OTHER.id, "Secret")
    response = await client.get(f"/api/v1/posts/{secret.id}")
    assert response.status_code == 404  # private group I'm not in: not found
    assert response.json()["error"]["code"] == "POST_NOT_FOUND"
    assert (await client.get(f"/api/v1/groups/{forum.private.id}/posts")).status_code == 404


@pytest.mark.db
async def test_post_detail_lists_replies_in_order(client, forum, db_session):
    post = await _post(db_session, forum.group, OTHER.id, "Question")
    db_session.add_all(
        [
            Reply(post_id=post.id, author_id=OTHER.id, body="plain", score=0,
                  moderation_status=ModerationStatus.APPROVED),
            Reply(post_id=post.id, author_id=OTHER.id, body="popular", score=5,
                  moderation_status=ModerationStatus.APPROVED),
            Reply(post_id=post.id, author_id=OTHER.id, body="accepted", score=1, is_accepted=True,
                  moderation_status=ModerationStatus.APPROVED),
            Reply(post_id=post.id, author_id=None, body="ai", is_ai_suggested=True,
                  moderation_status=ModerationStatus.APPROVED),
            Reply(post_id=post.id, author_id=OTHER.id, body="their pending",
                  moderation_status=ModerationStatus.PENDING),
            Reply(post_id=post.id, author_id=STUDENT.id, body="my pending",
                  moderation_status=ModerationStatus.PENDING),
        ]
    )  # fmt: skip
    await db_session.commit()

    detail = (await client.get(f"/api/v1/posts/{post.id}")).json()
    assert [r["body"] for r in detail["replies"]][:2] == ["accepted", "popular"]
    bodies = {r["body"] for r in detail["replies"]}
    assert "their pending" not in bodies and "my pending" in bodies
    ai = next(r for r in detail["replies"] if r["body"] == "ai")
    assert (ai["author"], ai["is_ai_suggested"]) == (None, True)
    assert detail["author"]["name"] == "Kasun" and detail["is_mine"] is False


@pytest.mark.db
async def test_only_the_author_can_edit(client, forum, db_session):
    mine = await _post(db_session, forum.group, STUDENT.id, "My question")
    theirs = await _post(db_session, forum.group, OTHER.id, "Their question")

    blocked = await client.patch(f"/api/v1/posts/{theirs.id}", json={"title": "Hacked title"})
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "NOT_POST_AUTHOR"

    edited = await client.patch(
        f"/api/v1/posts/{mine.id}",
        json={"title": "My better question", "topic_id": str(forum.topic.id), "tags": ["Cells"]},
    )
    assert edited.status_code == 200, edited.text
    body = edited.json()
    assert (body["title"], body["body"], body["topic"], body["tags"]) == (
        "My better question",
        "body",  # not sent, not changed
        "Forum topic",
        ["cells"],
    )
    cleared = await client.patch(f"/api/v1/posts/{mine.id}", json={"topic_id": None})
    assert cleared.json()["topic_id"] is None
    empty = await client.patch(f"/api/v1/posts/{mine.id}", json={"title": None})
    assert empty.status_code == 400
    assert empty.json()["error"]["code"] == "FIELD_REQUIRED"


@pytest.mark.db
async def test_delete_post(client, admin_client, forum, db_session):
    mine = await _post(db_session, forum.group, STUDENT.id, "Delete me")
    theirs = await _post(db_session, forum.group, OTHER.id, "Not yours")

    blocked = await client.delete(f"/api/v1/posts/{theirs.id}")
    assert blocked.status_code == 403
    assert (await client.delete(f"/api/v1/posts/{mine.id}")).status_code == 204
    gone = await client.get(f"/api/v1/posts/{mine.id}")
    assert gone.json()["error"]["code"] == "POST_NOT_FOUND"
    assert (await client.delete(f"/api/v1/posts/{mine.id}")).status_code == 404  # already gone

    async with _client_as(OTHER) as other:
        assert (await other.get(f"/api/v1/posts/{theirs.id}")).status_code == 200
    assert (await admin_client.delete(f"/api/v1/posts/{theirs.id}")).status_code == 204


# --------------------------------------------------------------------------- replies (no DB)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", f"/api/v1/posts/{uuid.uuid4()}/replies"),
        ("patch", f"/api/v1/replies/{uuid.uuid4()}"),
        ("delete", f"/api/v1/replies/{uuid.uuid4()}"),
        ("post", f"/api/v1/posts/{uuid.uuid4()}/accept/{uuid.uuid4()}"),
        ("delete", f"/api/v1/posts/{uuid.uuid4()}/accept"),
    ],
)
async def test_replies_require_login(anon_client, method, path):
    assert (await anon_client.request(method, path, json={})).status_code == 401


@pytest.mark.parametrize("body", [{}, {"body": ""}, {"body": "x" * 5001}])
async def test_reply_validation(client, body):
    response = await client.post(f"/api/v1/posts/{uuid.uuid4()}/replies", json=body)
    assert response.status_code == 422


# --------------------------------------------------------------------------- replies (DB)


async def _reply_count(client, post_id) -> int:  # type: ignore[no-untyped-def]
    return (await client.get(f"/api/v1/posts/{post_id}")).json()["reply_count"]


@pytest.mark.db
async def test_reply_and_reply_count(client, forum, db_session):
    post = await _post(db_session, forum.group, OTHER.id, "Question")

    response = await client.post(f"/api/v1/posts/{post.id}/replies", json={"body": "  Answer  "})
    assert response.status_code == 201, response.text
    reply = response.json()
    assert (reply["body"], reply["is_mine"], reply["author"]["name"]) == (
        "Answer",
        True,
        "Nethmi Perera",
    )
    assert (reply["moderation_status"], reply["is_accepted"]) == ("approved", False)
    assert await _reply_count(client, post.id) == 1

    # two replies at the same moment are both counted
    async with _client_as(OTHER) as other:
        await asyncio.gather(
            client.post(f"/api/v1/posts/{post.id}/replies", json={"body": "a"}),
            other.post(f"/api/v1/posts/{post.id}/replies", json={"body": "b"}),
        )
    assert await _reply_count(client, post.id) == 3


@pytest.mark.db
async def test_only_members_can_reply_and_only_to_visible_posts(client, forum, db_session):
    outside = CommunityGroup(name="Outside", slug=f"outside-{uuid.uuid4().hex[:8]}")
    db_session.add(outside)
    await db_session.flush()
    not_member = await _post(db_session, outside, OTHER.id, "Not my group")
    hidden = await _post(
        db_session, forum.group, OTHER.id, "Pending", moderation_status=ModerationStatus.PENDING
    )
    try:
        blocked = await client.post(f"/api/v1/posts/{not_member.id}/replies", json={"body": "x"})
        assert blocked.status_code == 403
        assert blocked.json()["error"]["code"] == "NOT_A_MEMBER"
        invisible = await client.post(f"/api/v1/posts/{hidden.id}/replies", json={"body": "x"})
        assert invisible.json()["error"]["code"] == "POST_NOT_FOUND"
    finally:
        await db_session.execute(delete(CommunityGroup).where(CommunityGroup.id == outside.id))
        await db_session.commit()


@pytest.mark.db
async def test_edit_and_delete_a_reply(client, admin_client, forum, db_session):
    post = await _post(db_session, forum.group, OTHER.id, "Question")
    mine = (await client.post(f"/api/v1/posts/{post.id}/replies", json={"body": "mine"})).json()
    async with _client_as(OTHER) as other:
        theirs = (
            await other.post(f"/api/v1/posts/{post.id}/replies", json={"body": "theirs"})
        ).json()

    blocked = await client.patch(f"/api/v1/replies/{theirs['id']}", json={"body": "hacked"})
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "NOT_REPLY_AUTHOR"
    edited = await client.patch(f"/api/v1/replies/{mine['id']}", json={"body": " better "})
    assert edited.json()["body"] == "better"

    assert (await client.delete(f"/api/v1/replies/{theirs['id']}")).status_code == 403
    assert (await client.delete(f"/api/v1/replies/{mine['id']}")).status_code == 204
    assert await _reply_count(client, post.id) == 1
    gone = await client.patch(f"/api/v1/replies/{mine['id']}", json={"body": "x"})
    assert gone.json()["error"]["code"] == "REPLY_NOT_FOUND"
    assert (await client.delete(f"/api/v1/replies/{mine['id']}")).status_code == 404

    assert (await admin_client.delete(f"/api/v1/replies/{theirs['id']}")).status_code == 204
    assert await _reply_count(client, post.id) == 0  # never below 0
    detail = (await client.get(f"/api/v1/posts/{post.id}")).json()
    assert detail["replies"] == []


@pytest.mark.db
async def test_accepting_an_answer(client, forum, db_session):
    mine = await _post(db_session, forum.group, STUDENT.id, "My question")
    other_post = await _post(db_session, forum.group, OTHER.id, "Their question")
    async with _client_as(OTHER) as other:
        first = (await other.post(f"/api/v1/posts/{mine.id}/replies", json={"body": "1"})).json()
        second = (await other.post(f"/api/v1/posts/{mine.id}/replies", json={"body": "2"})).json()
        elsewhere = (
            await other.post(f"/api/v1/posts/{other_post.id}/replies", json={"body": "x"})
        ).json()
        # only the post's author may accept
        blocked = await other.post(f"/api/v1/posts/{mine.id}/accept/{first['id']}")
        assert blocked.status_code == 403
        assert blocked.json()["error"]["code"] == "NOT_POST_AUTHOR"

    accepted = (await client.post(f"/api/v1/posts/{mine.id}/accept/{second['id']}")).json()
    assert accepted["accepted_reply_id"] == second["id"]
    assert [(r["id"], r["is_accepted"]) for r in accepted["replies"]][0] == (second["id"], True)

    switched = (await client.post(f"/api/v1/posts/{mine.id}/accept/{first['id']}")).json()
    assert switched["accepted_reply_id"] == first["id"]
    assert [r["id"] for r in switched["replies"] if r["is_accepted"]] == [first["id"]]

    wrong_post = await client.post(f"/api/v1/posts/{mine.id}/accept/{elsewhere['id']}")
    assert wrong_post.json()["error"]["code"] == "REPLY_NOT_FOUND"

    cleared = (await client.delete(f"/api/v1/posts/{mine.id}/accept")).json()
    assert cleared["accepted_reply_id"] is None
    assert not any(r["is_accepted"] for r in cleared["replies"])

    # deleting the accepted answer clears the acceptance
    await client.post(f"/api/v1/posts/{mine.id}/accept/{first['id']}")
    async with _client_as(OTHER) as other:
        assert (await other.delete(f"/api/v1/replies/{first['id']}")).status_code == 204
    after = (await client.get(f"/api/v1/posts/{mine.id}")).json()
    assert after["accepted_reply_id"] is None
