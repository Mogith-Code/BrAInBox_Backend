"""Profile setup (onboarding steps 1-3). Owner: Mogith."""

import pytest

from api.core import clock
from tests.conftest import STUDENT, make_api_client, student_claims

FULL_PROFILE = {
    "stream": "bio_science",
    "subject": "biology",
    "exam_year": clock.today().year + 1,
    "target_grade": "A",
    "confidence": 50,
    "study_days": ["sun", "mon", "tue", "thu", "sat", "mon"],
    "hours_per_day": 2.0,
    "preferred_time": "evening",
}


async def test_profiles_status_requires_login(anon_client):
    response = await anon_client.get("/api/v1/profiles/status")
    assert response.status_code == 401


async def test_options(client):
    response = await client.get("/api/v1/profile/options")
    assert response.status_code == 200
    options = response.json()
    year = clock.today().year
    assert options["exam_years"] == [year, year + 1, year + 2]
    assert options["streams"] == [
        {"id": "bio_science", "name": "Biological Science", "available": True}
    ]
    biology, chemistry, physics = options["subjects"]
    assert biology == {
        "id": "biology",
        "name": "Biology",
        "units": 10,
        "syllabus": "2025 syllabus",
        "available": True,
    }
    assert (chemistry["available"], physics["available"]) == (False, False)
    assert options["target_grades"] == ["A", "B", "C"]
    assert [t["id"] for t in options["preferred_times"]] == ["morning", "evening", "night"]


@pytest.mark.parametrize(
    "body",
    [
        {"confidence": 101},
        {"confidence": -1},
        {"hours_per_day": 2.25},
        {"hours_per_day": 0},
        {"hours_per_day": 6.5},
        {"study_days": []},
        {"study_days": ["monday"]},
        {"target_grade": "D"},
        {"preferred_time": "noon"},
    ],
)
async def test_patch_validation(client, body):
    response = await client.patch("/api/v1/profile", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.db
async def test_setup_steps_and_complete(student_in_db):
    async with make_api_client(user=STUDENT, claims=student_claims()) as c:
        empty = await c.get("/api/v1/profile")
        too_early = await c.post("/api/v1/profile/complete")
        chemistry = await c.patch("/api/v1/profile", json={"subject": "chemistry"})
        old_year = await c.patch("/api/v1/profile", json={"exam_year": 2020})
        step1 = await c.patch(
            "/api/v1/profile", json={"stream": "bio_science", "subject": "biology"}
        )
        saved = await c.patch("/api/v1/profile", json=FULL_PROFILE)
        done = await c.post("/api/v1/profile/complete")
        me = await c.get("/api/v1/auth/me")

    assert empty.json()["profile_completed"] is False
    assert empty.json()["stream"] is None
    assert too_early.json()["error"]["code"] == "PROFILE_INCOMPLETE"
    assert "exam_year" in too_early.json()["error"]["missing"]
    assert chemistry.json()["error"]["code"] == "SUBJECT_NOT_AVAILABLE"
    assert old_year.json()["error"]["code"] == "INVALID_EXAM_YEAR"
    assert step1.json()["subject"] == "biology"

    profile = saved.json()
    assert profile["study_days"] == ["mon", "tue", "thu", "sat", "sun"]  # sorted, no duplicates
    assert profile["weekly_hours"] == 10.0  # 2 h x 5 days
    assert profile["profile_completed"] is False
    assert done.json()["profile_completed"] is True
    assert me.json()["onboarding"]["profile_completed"] is True


@pytest.mark.db
async def test_complete_fails_when_a_field_is_cleared(student_in_db):
    async with make_api_client(user=STUDENT) as c:
        await c.patch("/api/v1/profile", json=FULL_PROFILE)
        await c.patch("/api/v1/profile", json={"preferred_time": None})
        response = await c.post("/api/v1/profile/complete")
    assert response.json()["error"]["code"] == "PROFILE_INCOMPLETE"
    assert response.json()["error"]["missing"] == ["preferred_time"]
