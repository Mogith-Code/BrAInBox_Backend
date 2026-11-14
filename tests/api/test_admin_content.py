"""Admin content library (content_admin.py): notes, short notes, diagrams. Owner: Samni."""

import uuid

import pytest
from sqlalchemy import delete, select

from shared.db.models import Note, Topic, Unit, Visual
from shared.enums import ContentSource, ContentStatus, VisualKind

URL = "/api/v1/admin/content"


@pytest.fixture
async def library(db_session, admin_in_db):  # type: ignore[no-untyped-def]
    unit = Unit(number=600_000 + uuid.uuid4().int % 99_999, title="Animal form and function")
    db_session.add(unit)
    await db_session.flush()
    topic = Topic(unit_id=unit.id, number="5.4", title="Excretion")
    db_session.add(topic)
    await db_session.flush()
    short = Note(topic_id=topic.id, title="Nephron short note", note_type="short",
                 body_md="## Nephron", status=ContentStatus.PENDING_REVIEW,
                 source=ContentSource.AI, model="gemini-2.5-flash",
                 prompt_version="notes/short.v2")  # fmt: skip
    old_full = Note(topic_id=topic.id, title="Old full note", note_type="full", body_md="old",
                    status=ContentStatus.APPROVED, source=ContentSource.ADMIN,
                    citations=[{"chunk_id": "c1"}])  # fmt: skip
    new_full = Note(topic_id=topic.id, title="New full note", note_type="full", body_md="new",
                    status=ContentStatus.PENDING_REVIEW, source=ContentSource.AI)  # fmt: skip
    archived = Note(topic_id=topic.id, title="Archived", note_type="full", body_md="x",
                    status=ContentStatus.ARCHIVED)  # fmt: skip
    diagram = Visual(topic_id=topic.id, kind=VisualKind.DIAGRAM, title="Nephron flow",
                     mermaid_code="flowchart LR\n A-->B", status=ContentStatus.DRAFT,
                     is_ai_generated=True, safety_passed=True)  # fmt: skip
    shared = Visual(topic_id=topic.id, kind=VisualKind.DIAGRAM, title="Approved heart",
                    mermaid_code="flowchart LR", status=ContentStatus.APPROVED)  # fmt: skip
    db_session.add_all([short, old_full, new_full, archived, diagram, shared])
    await db_session.commit()
    ids = {"unit": unit.id, "unit_number": unit.number, "topic": topic.id, "short": short.id,
           "old_full": old_full.id, "new_full": new_full.id, "archived": archived.id,
           "diagram": diagram.id, "shared": shared.id}  # fmt: skip
    yield ids
    await db_session.rollback()
    await db_session.execute(delete(Note).where(Note.topic_id == ids["topic"]))
    await db_session.execute(delete(Visual).where(Visual.topic_id == ids["topic"]))
    await db_session.execute(delete(Unit).where(Unit.id == ids["unit"]))
    await db_session.commit()


# --------------------------------------------------------------------------- auth + validation


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", URL, None),
        ("post", f"{URL}/{uuid.uuid4()}/approve", {}),
        ("post", f"{URL}/{uuid.uuid4()}/reject", {}),
        ("patch", f"{URL}/{uuid.uuid4()}", {"body_markdown": "x"}),
    ],
)
async def test_login_and_admin_role_needed(anon_client, client, method, path, body) -> None:  # type: ignore[no-untyped-def]
    kwargs = {"json": body} if body is not None else {}
    assert (await getattr(anon_client, method)(path, **kwargs)).status_code == 401
    assert (await getattr(client, method)(path, **kwargs)).status_code == 403


@pytest.mark.parametrize("query", ["type=video", "status=done", "unit=0", "unit=abc"])
async def test_bad_filters_are_422(admin_client, query: str) -> None:
    response = await admin_client.get(f"{URL}?{query}")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_bad_bodies_are_422(admin_client) -> None:
    some = uuid.uuid4()
    assert (
        await admin_client.patch(f"{URL}/{some}", json={"body_markdown": ""})
    ).status_code == 422
    assert (
        await admin_client.post(f"{URL}/{some}/approve", json={"note": "x" * 1001})
    ).status_code == 422
    assert (await admin_client.post(f"{URL}/bad/approve")).status_code == 422


# --------------------------------------------------------------------------- list


@pytest.mark.db
async def test_list_notes_and_diagrams_waiting(admin_client, library) -> None:  # type: ignore[no-untyped-def]
    response = await admin_client.get(URL, params={"unit": library["unit_number"]})

    assert response.status_code == 200
    by_title = {i["title"]: i for i in response.json()}
    # archived notes and already approved diagrams are not listed without a status filter
    assert set(by_title) == {"Nephron short note", "Old full note", "New full note", "Nephron flow"}
    short = by_title["Nephron short note"]
    assert set(short) == {
        "id", "title", "type", "syllabus_code", "unit_number", "status", "is_ai_generated",
        "model", "prompt_version", "body_markdown", "image_url", "auto_check", "updated_at",
    }  # fmt: skip
    assert (short["type"], short["syllabus_code"], short["status"]) == (
        "short_note",
        "5.4",
        "pending_review",
    )
    assert short["is_ai_generated"] is True and short["model"] == "gemini-2.5-flash"
    assert "No syllabus sources" in short["auto_check"]
    diagram = by_title["Nephron flow"]
    assert diagram["type"] == "diagram"
    assert diagram["body_markdown"].startswith("```mermaid")
    assert by_title["Old full note"]["type"] == "note"


@pytest.mark.db
async def test_filters(admin_client, library) -> None:  # type: ignore[no-untyped-def]
    async def titles(**params):  # type: ignore[no-untyped-def]
        params.setdefault("unit", library["unit_number"])
        return sorted(i["title"] for i in (await admin_client.get(URL, params=params)).json())

    assert await titles(type="diagram") == ["Nephron flow"]
    assert await titles(type="diagram", status="approved") == ["Approved heart"]
    assert await titles(type="note") == ["New full note", "Old full note"]
    assert await titles(type="short_note") == ["Nephron short note"]
    assert await titles(status="archived") == ["Archived"]
    assert await titles(unit=999_998) == []


# --------------------------------------------------------------------------- review + edit


@pytest.mark.db
async def test_approve_note_archives_the_older_one(admin_client, library, db_session) -> None:  # type: ignore[no-untyped-def]
    response = await admin_client.post(
        f"{URL}/{library['new_full']}/approve", json={"note": "Checked against the NIE guide"}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    old = await db_session.get(Note, library["old_full"], populate_existing=True)
    new = await db_session.get(Note, library["new_full"], populate_existing=True)
    assert old.status == ContentStatus.ARCHIVED
    assert new.review_comment == "Checked against the NIE guide"


@pytest.mark.db
async def test_approve_and_reject_diagrams(admin_client, library, db_session) -> None:  # type: ignore[no-untyped-def]
    approved = await admin_client.post(f"{URL}/{library['diagram']}/approve")
    rejected = await admin_client.post(f"{URL}/{library['shared']}/reject", json={"note": "blurry"})

    assert (approved.status_code, approved.json()["status"]) == (200, "approved")
    assert rejected.json()["status"] == "rejected"
    row = (
        await db_session.execute(
            select(Visual)
            .where(Visual.id == library["diagram"])
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert row.verified_by is not None  # students now see it as verified


@pytest.mark.db
async def test_reject_and_edit_a_note(admin_client, library) -> None:  # type: ignore[no-untyped-def]
    rejected = await admin_client.post(f"{URL}/{library['short']}/reject", json={})
    edited = await admin_client.patch(
        f"{URL}/{library['short']}", json={"body_markdown": "## Nephron\nFixed text"}
    )

    assert rejected.json()["status"] == "rejected"
    assert edited.status_code == 200
    assert edited.json()["body_markdown"] == "## Nephron\nFixed text"


@pytest.mark.db
async def test_diagram_text_is_not_editable_and_unknown_is_404(admin_client, library) -> None:  # type: ignore[no-untyped-def]
    diagram = await admin_client.patch(f"{URL}/{library['diagram']}", json={"body_markdown": "x"})
    unknown_edit = await admin_client.patch(f"{URL}/{uuid.uuid4()}", json={"body_markdown": "x"})
    unknown_review = await admin_client.post(f"{URL}/{uuid.uuid4()}/approve")

    assert diagram.status_code == 409
    assert diagram.json()["error"]["code"] == "CONTENT_NOT_EDITABLE"
    assert unknown_edit.status_code == 404
    assert unknown_review.json()["error"]["code"] == "CONTENT_NOT_FOUND"
