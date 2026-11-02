"""Tests for the visuals module (+ GET /jobs/{id} and the admin reports queue). Owner: Mogith.

The ai_service is replaced by `PipelineAIClient`, which runs the REAL visuals pipeline in this
process with the fake providers (no API keys, no network). Tests marked @pytest.mark.db need
PostgreSQL with `alembic upgrade head` and are skipped without it.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import delete, select

from ai_service.errors import UserInputError
from ai_service.pipelines.visuals import decide_visual
from ai_service.providers import set_providers
from ai_service.providers.diagram_renderer import FakeDiagramRenderer
from ai_service.providers.fakes import FakeLLM
from ai_service.rag.context_builder import BuiltContext
from ai_service.schemas.llm_outputs import VisualDecision
from api.core import storage
from api.core.ai_client import get_ai_client
from api.core.config import get_settings as get_api_settings
from api.core.errors import AppError, ServiceUnavailableError
from api.core.security import CurrentUser, get_current_user
from api.main import create_app
from api.modules.jobs.service import BUSY_ERROR
from api.modules.visuals.service import title_from, visual_out
from shared.db.models import AIJob, Topic, Unit, User, Visual, VisualReport
from shared.enums import ContentStatus, UserRole, VisualKind
from tests.conftest import ADMIN, STUDENT, _client

OTHER = CurrentUser(
    id=uuid.UUID(int=3), firebase_uid="test-other", email="other@test.local", role=UserRole.STUDENT
)
MERMAID = 'flowchart LR\n  A["1. Filtration"] --> B["2. Reabsorption"]'
GOOD_REQUEST = {
    "prompt": "Show how urine is formed",
    "visual_type": "process",
    "style": "flat_colour",
}


# --------------------------------------------------------------------------- helpers


class PipelineAIClient:
    """Stands in for the ai_service: runs ai_service/pipelines/visuals/decide_visual.run here.

    Input errors become AppError(422) exactly like api/core/ai_client.py does.
    """

    def __init__(self, down: bool = False):
        self.down = down
        self.payloads: list[dict[str, Any]] = []

    async def run_job(self, job_id, job_type, payload):  # type: ignore[no-untyped-def]
        self.payloads.append(payload)
        if self.down:
            raise ServiceUnavailableError(
                "The AI service is not available right now", code="AI_SERVICE_UNAVAILABLE"
            )
        try:
            result = await decide_visual.run(payload)
        except UserInputError as exc:
            raise AppError(exc.message, code=exc.code, status_code=422) from exc
        return {"job_id": job_id, "job_type": job_type, "result": result}


class DecisionLLM(FakeLLM):
    """Always gives this decision (the fake example with some fields changed)."""

    def __init__(self, **changes: Any):
        self.answer = {**VisualDecision.fake_example(), **changes}

    async def generate_json(self, prompt, schema, **kwargs):  # type: ignore[no-untyped-def]
        return schema.model_validate(self.answer)


def app_client(user: CurrentUser | None = STUDENT, ai: PipelineAIClient | None = None):  # type: ignore[no-untyped-def]
    app = create_app()
    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_ai_client] = lambda: ai or PipelineAIClient()
    return _client(app)


@pytest.fixture(autouse=True)
def no_rag(monkeypatch: pytest.MonkeyPatch) -> None:
    """The pipeline's RAG search returns nothing (keeps tests fast and independent)."""

    async def empty(query, topic_id):  # type: ignore[no-untyped-def]
        return BuiltContext(text="", citations=[])

    monkeypatch.setattr(decide_visual, "gather_context", empty)


@pytest.fixture
async def topic(db_session):  # type: ignore[no-untyped-def]
    """Two students + one unit/topic in the database; everything is removed afterwards."""
    for u in (STUDENT, OTHER):
        if await db_session.get(User, u.id) is None:
            db_session.add(User(id=u.id, firebase_uid=u.firebase_uid, role=UserRole.STUDENT))
    unit = Unit(number=800_000 + uuid.uuid4().int % 99_999, title="Excretion")
    db_session.add(unit)
    await db_session.flush()
    row = Topic(unit_id=unit.id, number="9.1", title="Urine formation")
    db_session.add(row)
    await db_session.commit()
    yield row
    ids = [STUDENT.id, OTHER.id]
    for stmt in (
        delete(Visual).where(Visual.topic_id == row.id),
        delete(Visual).where(Visual.created_by.in_(ids)),
        delete(AIJob).where(AIJob.requested_by.in_(ids)),
        delete(User).where(User.id.in_(ids)),
        delete(Unit).where(Unit.id == unit.id),
    ):
        await db_session.execute(stmt)
    await db_session.commit()


async def add_visual(session, topic_id, **fields):  # type: ignore[no-untyped-def]
    visual = Visual(
        topic_id=topic_id,
        kind=VisualKind.DIAGRAM,
        title=fields.pop("title", "A visual"),
        mermaid_code=fields.pop("mermaid_code", MERMAID),
        **fields,
    )
    session.add(visual)
    await session.commit()
    return visual


async def generate(c, topic_id=None, **changes):  # type: ignore[no-untyped-def]
    body = {**GOOD_REQUEST, **changes}
    if topic_id is not None:
        body["topic_id"] = str(topic_id)
    return await c.post("/api/v1/visuals/generate", json=body)


# --------------------------------------------------------------------------- no database


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", f"/api/v1/topics/{uuid.uuid4()}/visuals"),
        ("get", f"/api/v1/visuals/{uuid.uuid4()}"),
        ("post", "/api/v1/visuals/generate"),
        ("post", f"/api/v1/visuals/{uuid.uuid4()}/report"),
        ("get", f"/api/v1/jobs/{uuid.uuid4()}"),
    ],
)
async def test_endpoints_need_login(anon_client, method: str, path: str) -> None:
    response = await getattr(anon_client, method)(path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.parametrize(
    "changes",
    [
        {"prompt": "cell"},  # 4 characters, too short
        {"prompt": "    ab     "},  # spaces do not count
        {"prompt": "x" * 301},
        {"visual_type": "map"},
        {"style": "neon"},
        {"topic_id": "not-a-uuid"},
    ],
)
async def test_generate_rejects_bad_input(client, changes: dict[str, Any]) -> None:
    response = await client.post("/api/v1/visuals/generate", json={**GOOD_REQUEST, **changes})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_generate_needs_style(client) -> None:
    body = {"prompt": "Nephron structure", "visual_type": "structure"}
    response = await client.post("/api/v1/visuals/generate", json=body)
    assert response.status_code == 422


@pytest.mark.parametrize(
    "body", [{"reason": "ugly"}, {"reason": "unclear", "details": "x" * 501}, {}]
)
async def test_report_rejects_bad_input(client, body: dict[str, Any]) -> None:
    response = await client.post(f"/api/v1/visuals/{uuid.uuid4()}/report", json=body)
    assert response.status_code == 422


def test_title_from_prompt() -> None:
    assert title_from("  show   how urine is formed ") == "Show how urine is formed"


def test_visual_out_skips_broken_labels() -> None:
    visual = Visual(
        id=uuid.uuid4(),
        kind=VisualKind.DIAGRAM,
        title="Nephron",
        labels=[{"number": 1, "name": "Loop of Henle"}, {"name": "no number"}],
        is_ai_generated=True,
        verified_by=uuid.uuid4(),
        created_at=datetime.now(UTC),
    )
    out = visual_out(visual, "https://img.test/a.png")
    assert [label.name for label in out.labels] == ["Loop of Henle"]
    assert out.is_verified is True
    assert out.image_url == "https://img.test/a.png"


def test_dev_files_never_leave_the_visuals_folder(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    settings = get_api_settings()
    monkeypatch.setattr(settings, "LOCAL_STORAGE_DIR", str(tmp_path))
    (tmp_path / "visuals" / "t").mkdir(parents=True)
    (tmp_path / "visuals" / "t" / "v.png").write_bytes(b"png")
    (tmp_path / "uploads").mkdir()
    (tmp_path / "uploads" / "notes.pdf").write_bytes(b"%PDF")

    assert storage.local_file("visuals/t/v.png") == (tmp_path / "visuals" / "t" / "v.png").resolve()
    assert storage.local_file("visuals/../uploads/notes.pdf") is None
    assert storage.local_file("uploads/notes.pdf") is None
    assert storage.local_file("visuals/t/missing.png") is None
    monkeypatch.setattr(settings, "STORAGE_BUCKET", "real-bucket")
    assert storage.local_file("visuals/t/v.png") is None  # with a bucket: signed URLs only


async def test_dev_file_route_serves_pngs_without_login(anon_client, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(get_api_settings(), "LOCAL_STORAGE_DIR", str(tmp_path))
    (tmp_path / "visuals" / "t").mkdir(parents=True)
    (tmp_path / "visuals" / "t" / "v.png").write_bytes(b"\x89PNG fake")

    ok = await anon_client.get("/api/v1/files/visuals/t/v.png")
    assert ok.status_code == 200
    assert ok.headers["content-type"] == "image/png"
    missing = await anon_client.get("/api/v1/files/visuals/t/other.png")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "FILE_NOT_FOUND"


async def test_image_url_uses_the_address_the_app_called() -> None:
    url = await storage.public_image_url("visuals/t/v.png", "http://10.0.2.2:8000/")
    assert url == "http://10.0.2.2:8000/api/v1/files/visuals/t/v.png"
    assert await storage.public_image_url(None, "http://10.0.2.2:8000/") is None


# --------------------------------------------------------------------------- generate (database)


@pytest.mark.db
async def test_generate_mermaid_visual_end_to_end(topic, db_session) -> None:  # type: ignore[no-untyped-def]
    ai = PipelineAIClient()
    async with app_client(ai=ai) as c:
        response = await generate(c, topic.id)
        assert response.status_code == 202, response.text
        job_id = response.json()["job_id"]

        job = (await c.get(f"/api/v1/jobs/{job_id}")).json()
        assert job["status"] == "succeeded", job
        assert job["progress"] == 1.0
        visual_id = job["result"]["visual_id"]
        assert job["result"] == {"visual_id": visual_id}

        visual = (await c.get(f"/api/v1/visuals/{visual_id}")).json()
        listed = (await c.get(f"/api/v1/topics/{topic.id}/visuals")).json()

    assert ai.payloads[0]["visual_id"] == visual_id
    assert ai.payloads[0]["topic_title"] == "Urine formation"
    assert visual["kind"] == "diagram"
    assert visual["title"] == "Osmosis across a membrane"
    assert visual["mermaid_code"].startswith("flowchart LR")
    assert visual["image_url"] == f"http://test/api/v1/files/visuals/{topic.id}/{visual_id}.png"
    assert (visual["width"], visual["height"]) == (1, 1)  # the fake renderer's 1x1 PNG
    assert visual["style"] == "flat_colour"
    assert visual["is_ai_generated"] is True and visual["is_verified"] is False
    assert [label["number"] for label in visual["labels"]] == [1, 2, 3]
    assert visual["labels"][0]["x"] is None
    assert set(visual) == {
        "id", "title", "topic_id", "concept_id", "kind", "image_url", "mermaid_code",
        "alt_text", "labels", "style", "width", "height", "is_ai_generated", "is_verified",
        "created_at",
    }  # fmt: skip
    # The topic page shows the student's own draft
    assert listed["topic_title"] == "Urine formation"
    assert listed["unit_title"] == "Excretion"
    assert listed["unit_code"].isdigit()
    assert [v["id"] for v in listed["visuals"]] == [visual_id]

    row = await db_session.get(Visual, uuid.UUID(visual_id))
    await db_session.refresh(row)
    assert row.status == ContentStatus.DRAFT  # admins approve it to share it
    assert row.created_by == STUDENT.id
    assert row.safety_passed is True
    assert row.prompt == GOOD_REQUEST["prompt"]
    assert row.prompt_version == "visuals/decide_visual.v2"
    assert str(row.job_id) == job_id


@pytest.mark.db
async def test_generate_without_topic(topic) -> None:  # type: ignore[no-untyped-def]
    async with app_client() as c:
        job_id = (await generate(c)).json()["job_id"]
        job = (await c.get(f"/api/v1/jobs/{job_id}")).json()
        visual = (await c.get(f"/api/v1/visuals/{job['result']['visual_id']}")).json()
    assert visual["topic_id"] is None
    assert "/files/visuals/general/" in visual["image_url"]


@pytest.mark.db
async def test_kroki_down_still_makes_the_visual(topic) -> None:  # type: ignore[no-untyped-def]
    renderer = FakeDiagramRenderer()
    renderer.down = True
    set_providers(diagram=renderer)
    async with app_client() as c:
        job_id = (await generate(c, topic.id)).json()["job_id"]
        job = (await c.get(f"/api/v1/jobs/{job_id}")).json()
        visual = (await c.get(f"/api/v1/visuals/{job['result']['visual_id']}")).json()
    assert job["status"] == "succeeded"
    assert visual["image_url"] is None
    assert visual["mermaid_code"].startswith("flowchart")  # the app renders it itself


@pytest.mark.db
async def test_illustration_has_label_positions(topic) -> None:  # type: ignore[no-untyped-def]
    set_providers(
        llm=DecisionLLM(
            kind="illustration",
            mermaid_code=None,
            image_prompt="A nephron",
            labels=[{"number": 1, "name": "Glomerulus", "description": "Filters blood.", "x": 0.2, "y": 0.3}],
        )
    )  # fmt: skip
    async with app_client() as c:
        job_id = (await generate(c, topic.id, visual_type="structure")).json()["job_id"]
        job = (await c.get(f"/api/v1/jobs/{job_id}")).json()
        visual = (await c.get(f"/api/v1/visuals/{job['result']['visual_id']}")).json()
    assert visual["kind"] == "illustration"
    assert visual["mermaid_code"] is None
    assert visual["image_url"].endswith(".png")
    assert visual["labels"] == [
        {"number": 1, "name": "Glomerulus", "description": "Filters blood.", "x": 0.2, "y": 0.3}
    ]


@pytest.mark.db
async def test_not_biology_fails_and_hides_the_visual(topic, db_session) -> None:  # type: ignore[no-untyped-def]
    set_providers(llm=DecisionLLM(is_biology=False, mermaid_code=None))
    async with app_client() as c:
        job_id = (await generate(c, topic.id, prompt="Draw my favourite footballer")).json()[
            "job_id"
        ]
        job = (await c.get(f"/api/v1/jobs/{job_id}")).json()
        listed = (await c.get(f"/api/v1/topics/{topic.id}/visuals")).json()

    assert job["status"] == "failed"
    assert job["result"] is None
    assert job["error"] == "I can only draw Biology visuals."
    assert job["error_code"] == "NOT_BIOLOGY"
    assert listed["visuals"] == []
    row = (
        await db_session.execute(select(Visual).where(Visual.job_id == uuid.UUID(job_id)))
    ).scalar_one()
    assert row.status == ContentStatus.REJECTED
    assert row.safety_passed is False


@pytest.mark.db
async def test_ai_service_down_fails_with_a_friendly_error(topic) -> None:  # type: ignore[no-untyped-def]
    async with app_client(ai=PipelineAIClient(down=True)) as c:
        job_id = (await generate(c, topic.id)).json()["job_id"]
        job = (await c.get(f"/api/v1/jobs/{job_id}")).json()
        listed = (await c.get(f"/api/v1/topics/{topic.id}/visuals")).json()
    assert job["status"] == "failed"
    assert job["error"] == BUSY_ERROR
    assert listed["visuals"] == []  # the failed draft is archived, so it is hidden


@pytest.mark.db
async def test_daily_limit(topic, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(get_api_settings(), "VISUALS_DAILY_LIMIT", 2)
    async with app_client() as c:
        assert (await generate(c, topic.id)).status_code == 202
        assert (await generate(c, topic.id)).status_code == 202
        third = await generate(c, topic.id)
    assert third.status_code == 429
    error = third.json()["error"]
    assert error["code"] == "VISUAL_LIMIT_REACHED"
    assert 0 < error["retry_after"] <= 24 * 3600
    assert third.headers["Retry-After"] == str(error["retry_after"])


@pytest.mark.db
async def test_unknown_topic_is_404(topic) -> None:  # type: ignore[no-untyped-def]
    async with app_client() as c:
        generated = await generate(c, uuid.uuid4())
        listed = await c.get(f"/api/v1/topics/{uuid.uuid4()}/visuals")
    assert generated.status_code == 404
    assert generated.json()["error"]["code"] == "TOPIC_NOT_FOUND"
    assert listed.status_code == 404
    assert listed.json()["error"]["code"] == "TOPIC_NOT_FOUND"


# --------------------------------------------------------------------------- visibility


@pytest.mark.db
async def test_visibility_rules(topic, db_session) -> None:  # type: ignore[no-untyped-def]
    approved = await add_visual(
        db_session, topic.id, title="Approved", status=ContentStatus.APPROVED, verified_by=OTHER.id
    )
    mine = await add_visual(db_session, topic.id, title="My draft", created_by=STUDENT.id)
    others_draft = await add_visual(db_session, topic.id, title="Their draft", created_by=OTHER.id)
    my_archived = await add_visual(
        db_session, topic.id, title="Failed", created_by=STUDENT.id, status=ContentStatus.ARCHIVED
    )
    my_unfinished = await add_visual(
        db_session, topic.id, title="Still making", created_by=STUDENT.id, mermaid_code=None
    )

    async with app_client() as c:
        listed = (await c.get(f"/api/v1/topics/{topic.id}/visuals")).json()["visuals"]
        responses = {
            v.title: await c.get(f"/api/v1/visuals/{v.id}")
            for v in (approved, mine, others_draft, my_archived)
        }
        unknown = await c.get(f"/api/v1/visuals/{uuid.uuid4()}")

    assert [v["title"] for v in listed] == ["My draft", "Approved"]  # newest first
    assert my_unfinished.id not in {uuid.UUID(v["id"]) for v in listed}
    assert listed[1]["is_verified"] is True
    assert listed[1]["is_ai_generated"] is False
    assert responses["Approved"].status_code == 200
    assert responses["My draft"].status_code == 200
    for hidden in ("Their draft", "Failed"):
        assert responses[hidden].status_code == 404
        assert responses[hidden].json()["error"]["code"] == "VISUAL_NOT_FOUND"
    assert unknown.status_code == 404

    # The other student sees their own draft
    async with app_client(user=OTHER) as c:
        theirs = await c.get(f"/api/v1/visuals/{others_draft.id}")
    assert theirs.status_code == 200


# --------------------------------------------------------------------------- reports + admin


@pytest.mark.db
async def test_report_once_while_pending(topic, db_session) -> None:  # type: ignore[no-untyped-def]
    visual = await add_visual(db_session, topic.id, status=ContentStatus.APPROVED)
    others_draft = await add_visual(db_session, topic.id, created_by=OTHER.id)
    body = {"reason": "wrong_label", "details": "  Label 2 should be the PCT.  "}

    async with app_client() as c:
        first = await c.post(f"/api/v1/visuals/{visual.id}/report", json=body)
        again = await c.post(f"/api/v1/visuals/{visual.id}/report", json={"reason": "unclear"})
        hidden = await c.post(f"/api/v1/visuals/{others_draft.id}/report", json=body)
    async with app_client(user=OTHER) as c:
        other_student = await c.post(f"/api/v1/visuals/{visual.id}/report", json=body)

    assert first.status_code == 201, first.text
    report = first.json()
    assert (report["reason"], report["status"]) == ("wrong_label", "pending")
    assert report["details"] == "Label 2 should be the PCT."
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "ALREADY_REPORTED"
    assert hidden.status_code == 404
    assert other_student.status_code == 201  # a different student may report it too

    rows = (
        await db_session.execute(select(VisualReport).where(VisualReport.visual_id == visual.id))
    ).scalars()
    assert {r.user_id for r in rows} == {STUDENT.id, OTHER.id}


@pytest.mark.db
async def test_admin_reports_queue_shows_visual(topic, db_session) -> None:  # type: ignore[no-untyped-def]
    visual = await add_visual(
        db_session,
        topic.id,
        title="Nephron",
        status=ContentStatus.APPROVED,
        image_path=f"visuals/{topic.id}/nephron.png",
    )
    async with app_client() as c:
        await c.post(f"/api/v1/visuals/{visual.id}/report", json={"reason": "inaccurate"})
    async with app_client(user=ADMIN) as c:
        queue = await c.get("/api/v1/admin/moderation/reports")
    async with app_client() as c:
        forbidden = await c.get("/api/v1/admin/moderation/reports")

    assert queue.status_code == 200
    [item] = [r for r in queue.json() if r["visual_id"] == str(visual.id)]
    assert item["target_type"] == "visual"
    assert item["visual_title"] == "Nephron"
    assert item["image_url"] == f"http://test/api/v1/files/visuals/{topic.id}/nephron.png"
    assert item["reason"] == "inaccurate"
    assert item["reported_by"] == str(STUDENT.id)
    assert forbidden.status_code == 403


# --------------------------------------------------------------------------- jobs


@pytest.mark.db
async def test_jobs_are_private(topic) -> None:  # type: ignore[no-untyped-def]
    async with app_client() as c:
        job_id = (await generate(c, topic.id)).json()["job_id"]
    async with app_client(user=OTHER) as c:
        other = await c.get(f"/api/v1/jobs/{job_id}")
        unknown = await c.get(f"/api/v1/jobs/{uuid.uuid4()}")
    async with app_client(user=ADMIN) as c:
        admin = await c.get(f"/api/v1/jobs/{job_id}")

    assert other.status_code == 404
    assert other.json()["error"]["code"] == "JOB_NOT_FOUND"
    assert unknown.status_code == 404
    assert admin.status_code == 200
    assert admin.json()["job_type"] == "generate_visual"
