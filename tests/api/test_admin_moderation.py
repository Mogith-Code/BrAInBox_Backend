"""Admin moderation queue + study groups (moderation_admin.py). Owner: Mogith."""

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete, select

from api.core import clock
from shared.db.models import (
    CommunityGroup,
    ContentReport,
    GroupMember,
    Notification,
    Post,
    Reply,
    User,
    Visual,
    VisualReport,
)
from shared.enums import ContentStatus, ModerationStatus, UserRole, VisualKind

REPORTS = "/api/v1/admin/moderation/reports"
GROUPS = "/api/v1/admin/community/groups"
TAG = "admmod"


@pytest.fixture
async def queue(db_session, admin_in_db):  # type: ignore[no-untyped-def]
    """A post with 2 reports (AI flagged), a reply with 1, a visual with 1, one closed report."""
    now = clock.now()
    author = User(firebase_uid=f"{TAG}-author", email=f"author.{TAG}@test.local",
                  display_name="Kavindu Silva", role=UserRole.STUDENT)  # fmt: skip
    reporter = User(firebase_uid=f"{TAG}-rep", email=f"rep.{TAG}@test.local", role=UserRole.STUDENT)
    db_session.add_all([author, reporter])
    await db_session.flush()
    group = CommunityGroup(name=f"Unit 6 Genetics {TAG}", slug=f"unit-6-{TAG}")
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupMember(group_id=group.id, user_id=author.id, role="moderator"))
    post = Post(group_id=group.id, author_id=author.id, title="Leaked papers",
                body="Join my WhatsApp", moderation_reason="Spam / external link",
                moderation_score=Decimal("0.960"))  # fmt: skip
    db_session.add(post)
    await db_session.flush()
    reply = Reply(post_id=post.id, author_id=author.id, body="copy this answer")
    visual = Visual(kind=VisualKind.DIAGRAM, title="Nephron", mermaid_code="flowchart LR",
                    status=ContentStatus.APPROVED, created_by=author.id, prompt="nephron")  # fmt: skip
    db_session.add_all([reply, visual])
    await db_session.flush()
    first = ContentReport(reporter_id=reporter.id, target_type="post", target_id=post.id,
                          reason="spam", created_at=now - timedelta(hours=3))  # fmt: skip
    second = ContentReport(reporter_id=author.id, target_type="post", target_id=post.id,
                           reason="spam", created_at=now - timedelta(hours=1))  # fmt: skip
    on_reply = ContentReport(reporter_id=reporter.id, target_type="reply", target_id=reply.id,
                             reason="other", created_at=now - timedelta(hours=2))  # fmt: skip
    closed = ContentReport(reporter_id=reporter.id, target_type="reply", target_id=reply.id,
                           reason="other", status=ModerationStatus.APPROVED)  # fmt: skip
    on_visual = VisualReport(visual_id=visual.id, user_id=reporter.id, reason="unclear",
                             details="Labels overlap", created_at=now - timedelta(minutes=30))  # fmt: skip
    db_session.add_all([first, second, on_reply, closed, on_visual])
    await db_session.commit()
    ids = {
        "post": post.id, "reply": reply.id, "visual": visual.id, "group": group.id,
        "author": author.id, "first": first.id, "second": second.id, "on_reply": on_reply.id,
        "closed": closed.id, "on_visual": on_visual.id,
    }  # fmt: skip
    yield ids
    await db_session.rollback()
    await db_session.execute(
        delete(ContentReport).where(ContentReport.target_id.in_([ids["post"], ids["reply"]]))
    )
    await db_session.execute(delete(Visual).where(Visual.id == ids["visual"]))
    await db_session.execute(delete(CommunityGroup).where(CommunityGroup.slug.like(f"%{TAG}%")))
    await db_session.execute(delete(User).where(User.email.like(f"%{TAG}%")))
    await db_session.commit()


@pytest.fixture
async def clean_groups(db_session):  # type: ignore[no-untyped-def]
    yield
    await db_session.rollback()
    await db_session.execute(delete(CommunityGroup).where(CommunityGroup.name.like("%Mod test%")))
    await db_session.commit()


def mine(items: list[dict], ids: dict) -> list[dict]:
    targets = {str(ids[k]) for k in ("post", "reply", "visual")}
    return [i for i in items if i["target_id"] in targets]


# --------------------------------------------------------------------------- auth + validation


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", REPORTS, None),
        ("post", f"{REPORTS}/{uuid.uuid4()}/resolve", {"action": "keep"}),
        ("get", GROUPS, None),
        ("post", GROUPS, {"name": "Mod test"}),
    ],
)
async def test_login_and_admin_role_needed(anon_client, client, method, path, body) -> None:  # type: ignore[no-untyped-def]
    kwargs = {"json": body} if body else {}
    assert (await getattr(anon_client, method)(path, **kwargs)).status_code == 401
    assert (await getattr(client, method)(path, **kwargs)).status_code == 403


@pytest.mark.parametrize(
    ("path", "body"),
    [
        (f"{REPORTS}/{uuid.uuid4()}/resolve", {"action": "ban"}),
        (f"{REPORTS}/{uuid.uuid4()}/resolve", {}),
        (f"{REPORTS}/not-an-id/resolve", {"action": "keep"}),
        (GROUPS, {"name": " a "}),
        (GROUPS, {"name": "x" * 121}),
    ],
)
async def test_bad_input_is_422(admin_client, path: str, body: dict) -> None:
    response = await admin_client.post(path, json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


# --------------------------------------------------------------------------- queue


@pytest.mark.db
async def test_queue_groups_reports_per_target_oldest_first(admin_client, queue) -> None:  # type: ignore[no-untyped-def]
    response = await admin_client.get(REPORTS)

    assert response.status_code == 200
    items = mine(response.json(), queue)
    assert [i["target_type"] for i in items] == ["post", "reply", "visual"]
    post, reply, visual = items
    assert set(post) == {
        "id", "target_type", "target_id", "reason", "details", "author_handle", "group_name",
        "text", "visual_title", "image_url", "ai_flag_label", "ai_flag_score", "report_count",
        "created_at",
    }  # fmt: skip
    assert post["id"] == str(queue["first"])  # the oldest open report
    assert post["report_count"] == 2
    assert (post["ai_flag_label"], post["ai_flag_score"]) == ("Spam / external link", 0.96)
    assert post["author_handle"] == "Kavindu Silva"
    assert post["group_name"] == f"Unit 6 Genetics {TAG}"
    assert post["text"].startswith("Leaked papers")
    assert reply["report_count"] == 1  # the closed report is not counted
    assert reply["group_name"] == f"Unit 6 Genetics {TAG}"
    assert (visual["visual_title"], visual["details"]) == ("Nephron", "Labels overlap")


@pytest.mark.db
async def test_keep_dismisses_every_report_of_the_target(admin_client, queue, db_session) -> None:  # type: ignore[no-untyped-def]
    response = await admin_client.post(
        f"{REPORTS}/{queue['first']}/resolve", json={"action": "keep"}
    )
    again = await admin_client.post(f"{REPORTS}/{queue['second']}/resolve", json={"action": "keep"})

    assert response.status_code == 204
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "REPORT_ALREADY_RESOLVED"
    remaining = mine((await admin_client.get(REPORTS)).json(), queue)
    assert [i["target_type"] for i in remaining] == ["reply", "visual"]
    post = await db_session.get(Post, queue["post"], populate_existing=True)
    assert post.moderation_status == ModerationStatus.PENDING  # kept as it was


@pytest.mark.db
async def test_warn_notifies_the_author(admin_client, queue, db_session) -> None:  # type: ignore[no-untyped-def]
    response = await admin_client.post(
        f"{REPORTS}/{queue['on_reply']}/resolve", json={"action": "warn"}
    )
    assert response.status_code == 204
    await db_session.rollback()
    notes = (
        (
            await db_session.execute(
                select(Notification).where(Notification.user_id == queue["author"])
            )
        )
        .scalars()
        .all()
    )
    assert [n.title for n in notes] == ["A moderator reviewed your reply"]


@pytest.mark.db
async def test_remove_hides_post_and_visual(admin_client, queue, db_session) -> None:  # type: ignore[no-untyped-def]
    post = await admin_client.post(
        f"{REPORTS}/{queue['second']}/resolve", json={"action": "remove"}
    )
    visual = await admin_client.post(
        f"{REPORTS}/{queue['on_visual']}/resolve", json={"action": "remove"}
    )

    assert (post.status_code, visual.status_code) == (204, 204)
    row = (
        await db_session.execute(
            select(Post).where(Post.id == queue["post"]).execution_options(populate_existing=True)
        )
    ).scalar_one()
    vis = (
        await db_session.execute(
            select(Visual)
            .where(Visual.id == queue["visual"])
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert row.moderation_status == ModerationStatus.REMOVED
    assert vis.status == ContentStatus.REJECTED
    assert [i["target_type"] for i in mine((await admin_client.get(REPORTS)).json(), queue)] == [
        "reply"
    ]


@pytest.mark.db
async def test_unknown_report_is_404(admin_client, admin_in_db) -> None:  # type: ignore[no-untyped-def]
    response = await admin_client.post(f"{REPORTS}/{uuid.uuid4()}/resolve", json={"action": "keep"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "REPORT_NOT_FOUND"


# --------------------------------------------------------------------------- groups


@pytest.mark.db
async def test_groups_list_members_and_moderator(admin_client, queue) -> None:  # type: ignore[no-untyped-def]
    response = await admin_client.get(GROUPS)
    assert response.status_code == 200
    [group] = [g for g in response.json() if g["id"] == str(queue["group"])]
    assert group == {
        "id": str(queue["group"]),
        "name": f"Unit 6 Genetics {TAG}",
        "members": 1,
        "moderator_name": "Kavindu Silva",
        "is_open": True,
    }


@pytest.mark.db
async def test_create_group_and_name_taken(admin_client, admin_in_db, clean_groups) -> None:  # type: ignore[no-untyped-def]
    created = await admin_client.post(GROUPS, json={"name": "  Mod test   Plants "})
    taken = await admin_client.post(GROUPS, json={"name": "mod test plants"})

    assert created.status_code == 201
    assert created.json()["name"] == "Mod test Plants"
    assert (created.json()["members"], created.json()["moderator_name"]) == (0, None)
    assert taken.status_code == 409
    assert taken.json()["error"]["code"] == "GROUP_NAME_TAKEN"
    listed = [g["name"] for g in (await admin_client.get(GROUPS)).json()]
    assert "Mod test Plants" in listed
