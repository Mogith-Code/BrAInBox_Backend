"""scripts/seed_admin_demo.py: demo data for every admin screen; idempotent; never in production."""

import pytest
from sqlalchemy import delete, select

from scripts import seed_admin_demo
from scripts.seed_admin_demo import UNITS, clear, refuse_in_production, seed
from shared.db.models import Unit
from shared.settings import get_shared_settings
from tests.conftest import ADMIN, make_api_client


def test_refuses_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_shared_settings()
    for value in ("prod", "production", "Production"):
        monkeypatch.setattr(settings, "ENVIRONMENT", value)
        with pytest.raises(SystemExit):
            refuse_in_production()
    monkeypatch.setattr(settings, "ENVIRONMENT", "dev")
    refuse_in_production()  # fine in dev


def test_demo_users_are_easy_to_find() -> None:
    assert seed_admin_demo.email("nethmi") == "nethmi@demo.brainbox.local"


@pytest.fixture
async def demo(db_session, admin_in_db):  # type: ignore[no-untyped-def]
    numbers = [n for n, _, _ in UNITS]
    existing = set(
        (await db_session.execute(select(Unit.number).where(Unit.number.in_(numbers)))).scalars()
    )
    await clear(db_session)
    yield
    await db_session.rollback()
    await clear(db_session)
    # Units the seed had to create (the test database has no real syllabus) go too.
    new = [n for n in numbers if n not in existing]
    if new:
        await db_session.execute(delete(Unit).where(Unit.number.in_(new)))
        await db_session.commit()


@pytest.mark.db
async def test_seed_is_idempotent_and_fills_every_screen(db_session, demo) -> None:  # type: ignore[no-untyped-def]
    first = await seed(db_session)
    second = await seed(db_session)

    assert first["users"] == 7  # 6 students + the demo content author
    assert first["questions"] >= 8 and first["past_paper_questions"] == 3
    assert second == {}  # nothing added the second time

    async with make_api_client(user=ADMIN) as c:
        students = (await c.get("/api/v1/admin/users", params={"search": "demo.brainbox"})).json()
        reports = (await c.get("/api/v1/admin/moderation/reports")).json()
        groups = (await c.get("/api/v1/admin/community/groups")).json()
        content = (await c.get("/api/v1/admin/content")).json()
        bank = (await c.get("/api/v1/admin/questions", params={"page_size": 100})).json()
        quality = (await c.get("/api/v1/admin/questions/quality")).json()
        papers = (await c.get("/api/v1/admin/questions/past-papers")).json()
        dashboard = await c.get("/api/v1/admin/dashboard")

    assert students["total"] == 6
    assert {s["status"] for s in students["items"]} == {"active", "suspended", "inactive"}
    assert {r["target_type"] for r in reports} >= {"post", "reply", "visual"}
    spam = next(r for r in reports if r["ai_flag_label"] == "Spam / external link")
    assert spam["report_count"] == 3
    assert "Unit 6 · Genetics" in {g["name"] for g in groups}
    assert {"short_note", "note", "diagram"} <= {i["type"] for i in content}
    assert bank["past_paper_percent"] >= 0 and bank["total"] >= 8
    assert any(i["student_reports"] for i in quality["items"])
    [paper] = [p for p in papers if p["year"] == 2019]
    assert (paper["extraction"], paper["low_confidence"], paper["scheme_linked"]) == (
        "low_confidence",
        1,
        True,
    )
    assert dashboard.status_code == 200
    kpis = {k["kind"]: k["value"] for k in dashboard.json()["kpis"]}
    assert kpis["quizzes"] >= 3 and kpis["aiReview"] >= 3 and kpis["reports"] >= 3
    assert dashboard.json()["missed_topics"]

    assert await clear(db_session) == 7
