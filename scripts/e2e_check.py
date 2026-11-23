"""End-to-end check of the main student and admin journeys, through the real API.

Run it against a LOCAL API that uses a TEST database, never the team database:

    $env:DATABASE_URL = "postgresql+asyncpg://postgres@127.0.0.1:60343/brainbox_e2e"
    $env:ENVIRONMENT = "dev"
    $env:DEV_LOGIN_ENABLED = "true"
    python -m uvicorn api.main:app --port 8011
    python scripts/e2e_check.py --api http://127.0.0.1:8011

Result of each step:
    PASS     it works
    FAIL     a bug: the script exits with code 1
    CONTENT  the code works, but the database needs more content (questions, documents...)
"""

import argparse
import sys
from typing import Any
from urllib.parse import urlparse

import httpx

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
# The smallest valid-looking PNG header: enough for the photo upload check.
TEST_PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
results: list[tuple[str, str, str]] = []


def report(status: str, step: str, detail: str = "") -> None:
    results.append((status, step, detail))
    print(f"{status:8}{step}" + (f"  ({detail})" if detail else ""))


def check(step: str, response: httpx.Response, *allowed: int) -> Any:
    """PASS when the status code is expected, otherwise FAIL. Returns the JSON body."""
    expected = allowed or (200,)
    if response.status_code not in expected:
        report("FAIL", step, f"HTTP {response.status_code}: {response.text[:160]}")
        return None
    report("PASS", step)
    return response.json() if response.content else {}


def items(body: Any) -> list[Any]:
    """Lists arrive as {"items": [...]} or as a plain list."""
    if isinstance(body, dict):
        return list(body.get("items", []))
    return list(body or [])


def profile_journey(student: httpx.Client) -> None:
    account = {"full_name": "E2E Student", "consent": True}
    check("Student registers", student.post("/auth/register", json=account), 200, 201)
    check("Student account opens", student.get("/auth/me"))
    options = check("Profile options load", student.get("/profile/options")) or {}
    years = options.get("exam_years") or []
    setup = {
        "stream": "bio_science",
        "subject": "biology",
        "exam_year": years[0] if years else None,
        "target_grade": "A",
        "confidence": 60,
        "study_days": ["mon", "wed", "fri"],
        "hours_per_day": 2,
        "preferred_time": "evening",
    }
    check("Profile setup saves", student.patch("/profile", json=setup))
    check("Profile setup finishes", student.post("/profile/complete"))
    check("Name and phone save", student.patch("/auth/me", json={"full_name": "E2E Student"}))
    body = check("Bio saves", student.patch("/profile/details", json={"bio": "Future doctor"}))
    if body and body.get("bio") != "Future doctor":
        report("FAIL", "Bio is returned", str(body.get("bio")))
    files = {"file": ("me.png", TEST_PNG, "image/png")}
    body = check("Profile photo uploads", student.post("/profile/avatar", files=files))
    if body and not body.get("avatar_url"):
        report("FAIL", "Profile photo has a link")
    check("Profile photo removes", student.delete("/profile/avatar"))
    check("Profile page loads", student.get("/profile/overview"))


def learn_journey(student: httpx.Client) -> None:
    subjects = items(check("Subjects load", student.get("/learn/subjects")))
    biology = next((s for s in subjects if s.get("name") == "Biology"), None)
    if biology is None:
        report("CONTENT", "Biology subject", "run scripts/seed_customer.py")
        return
    units = items(check("Units load", student.get(f"/learn/subjects/{biology['id']}/units")))
    bad = with_notes = total = 0
    for unit in units:
        detail = student.get(f"/learn/units/{unit['id']}")
        if detail.status_code != 200:
            bad += 1
            continue
        for topic in detail.json().get("topics", []):
            total += 1
            page = student.get(f"/learn/topics/{topic['id']}")
            # The app reads the breadcrumb's unit, so it must always be there.
            if page.status_code != 200 or "unit" not in page.json().get("breadcrumb", {}):
                bad += 1
            notes = student.get(f"/learn/topics/{topic['id']}/notes", params={"type": "full"})
            with_notes += notes.status_code == 200
    report("FAIL" if bad else "PASS", f"All {total} topic pages open", f"{bad} broken")
    if with_notes < total:
        report("CONTENT", "Topic notes", f"{with_notes} of {total} topics have approved notes")


def practice_journey(student: httpx.Client) -> None:
    check("Practice tab loads", student.get("/practice/hub"))
    diagnostic = student.post("/diagnostic/start")
    if diagnostic.status_code == 409:
        message = diagnostic.json()["error"]["message"]
        report("CONTENT", "Diagnostic test", message)
    else:
        check("Diagnostic test starts", diagnostic, 200, 201)

    started = student.post("/quizzes", json={"count": 5})
    if started.status_code == 422:
        report("CONTENT", "Quiz", "no approved questions")
        return
    quiz = check("Quiz starts", started, 200, 201)
    if not quiz:
        return
    for question in quiz.get("questions", []):
        answer = {"question_id": question["id"], "option_id": question["options"][0]["id"]}
        saved = student.post(f"/quizzes/{quiz['quiz_id']}/responses", json=answer)
        if saved.status_code >= 400:
            report("FAIL", "Quiz answer saves", saved.text[:160])
            return
    check("Quiz submits with a result", student.post(f"/quizzes/{quiz['quiz_id']}/submit"))


def community_journey(student: httpx.Client, other: httpx.Client) -> None:
    groups = items(check("Community groups load", student.get("/groups")))
    if not groups:
        report("CONTENT", "Community groups", "run scripts/seed_customer.py")
        return
    group = groups[0]["id"]
    check("First person joins a group", student.post(f"/groups/{group}/join"))
    check("Second person joins the same group", other.post(f"/groups/{group}/join"))
    new_post = {"title": "Osmosis help", "body": "How does water potential change in a cell?"}
    post = check("First person posts", student.post(f"/groups/{group}/posts", json=new_post), 201)
    if not post:
        return
    if post.get("moderation_status") != "approved":
        # Posts stay hidden until the AI moderator (or an admin) approves them.
        report("FAIL", "Post is published", "AI service is not running: use python run_dev.py")
        return
    feed = items(check("Second person reads the feed", other.get(f"/groups/{group}/posts")))
    if not any(p["id"] == post["id"] for p in feed):
        report("FAIL", "Second person sees the post")
    reply = {"body": "It becomes less negative as water enters."}
    check("Second person replies", other.post(f"/posts/{post['id']}/replies", json=reply), 201)
    check("First person sees the thread", student.get(f"/posts/{post['id']}"))


def admin_journey(admin: httpx.Client) -> None:
    check("Admin dashboard loads", admin.get("/admin/dashboard"))
    check("Admin users load", admin.get("/admin/users"))
    bank = check("Admin question bank loads", admin.get("/admin/questions"))
    if bank is not None and not items(bank):
        report("CONTENT", "Question bank", "no questions")
    papers = check("Admin past papers load", admin.get("/admin/questions/past-papers"))
    if papers is not None and not items(papers):
        report("CONTENT", "Past papers", "upload papers in Admin > Past papers")
    sources = check("Admin RAG sources load", admin.get("/admin/rag/sources"))
    if sources is not None and not items(sources):
        report("CONTENT", "AI paper generation", "upload approved documents in Admin > RAG sources")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8011")
    args = parser.parse_args()
    if urlparse(args.api).hostname not in LOCAL_HOSTS:
        print("Refusing to run: this script creates test data, so use a local API only.")
        return 2

    base = f"{args.api.rstrip('/')}/api/v1"
    student = httpx.Client(base_url=base, headers={"Authorization": "Bearer dev-token"}, timeout=60)
    admin = httpx.Client(base_url=base, headers={"Authorization": "Bearer dev-admin"}, timeout=60)

    profile_journey(student)
    learn_journey(student)
    practice_journey(student)
    community_journey(student, admin)
    admin_journey(admin)

    counts = {s: sum(r[0] == s for r in results) for s in ("PASS", "FAIL", "CONTENT")}
    print(f"\n{counts['PASS']} passed, {counts['FAIL']} failed, {counts['CONTENT']} need content")
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
