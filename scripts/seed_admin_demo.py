"""Demo data for every admin portal screen (local development only).

    python -m scripts.seed_admin_demo            # add the demo data (safe to run again)
    python -m scripts.seed_admin_demo --clear    # remove it again

What it adds (only what is missing, so running it twice changes nothing):
  * 6 students (one suspended, one inactive) with schools, districts, mastery and study days
  * study groups, posts, a reply, an AI-flagged post and open reports (moderation)
  * questions: approved MCQs with options + misconceptions, AI questions waiting for review
    (with AI checks and student reports), a past-paper question
  * notes waiting for review and a diagram waiting for review (content library)
  * a finished quiz with wrong answers today (dashboard, most missed topics)
  * a past paper with extracted questions (past papers screen)

Every demo row is owned by a demo user (email ...@demo.brainbox.local), which is how --clear
finds them. Units/topics are only created when your syllabus does not have them yet, and are
never removed. It refuses to run when ENVIRONMENT is prod / production.
"""

import argparse
import asyncio
import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

# Works as `python scripts/seed_admin_demo.py` AND `python -m scripts.seed_admin_demo`
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from shared.db.models import (  # noqa: E402
    Attempt,
    CommunityGroup,
    ContentReport,
    GroupMember,
    MCQOption,
    Misconception,
    Note,
    Paper,
    PastPaper,
    PastPaperQuestion,
    Post,
    Question,
    QuestionReport,
    QuestionReview,
    Reply,
    Response,
    StudentProfile,
    StudyActivity,
    Topic,
    Unit,
    UnitMastery,
    User,
    Visual,
    VisualReport,
)
from shared.db.session import SessionLocal  # noqa: E402
from shared.enums import (  # noqa: E402
    ContentSource,
    ContentStatus,
    Difficulty,
    ModerationStatus,
    QuestionType,
    UserRole,
    VisualKind,
)
from shared.settings import get_shared_settings  # noqa: E402

DEMO_DOMAIN = "demo.brainbox.local"
PRODUCTION = {"prod", "production"}

# (key, name, school, district, exam year offset, active, days since last study, mastery)
STUDENTS = [
    ("nethmi", "Nethmi Perera", "Visakha Vidyalaya", "Colombo", 1, True, 0, 74),
    ("kavindu", "Kavindu Silva", "Trinity College", "Kandy", 1, True, 1, 58),
    ("sanduni", "Sanduni Fernando", "Southlands College", "Galle", 0, True, 2, 81),
    ("ruwan", "Ruwan Jayasinghe", "Maliyadeva College", "Kurunegala", 1, False, 6, 42),
    ("ishara", "Ishara Kumari", "Vembadi Girls' High School", "Jaffna", 1, True, 0, 66),
    ("tharindu", "Tharindu Bandara", "Rahula College", "Matara", 0, True, 34, 31),
]
UNITS = [
    (2, "Chemical and Cellular Basis of Life", [("2.3", "Enzymes")]),
    (5, "Animal Form and Function", [("5.4", "Excretion and the nephron")]),
    (
        6,
        "Genetics",
        [("6.1", "Mendelian inheritance"), ("6.2", "Linkage and sex-linked inheritance")],
    ),
]
GROUPS = [
    ("demo-unit-6-genetics", "Unit 6 · Genetics", "nethmi"),
    ("demo-unit-5-human-body", "Unit 5 · Human body", None),
    ("demo-past-paper-discussion", "Past paper discussion", "sanduni"),
]


def email(key: str) -> str:
    return f"{key}@{DEMO_DOMAIN}"


class Seeder:
    """Get-or-create helpers; `added` counts the new rows per table."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.added: dict[str, int] = {}

    async def first(self, stmt: Any) -> Any:
        return (await self.session.execute(stmt.limit(1))).scalars().first()

    def add(self, row: Any) -> Any:
        self.session.add(row)
        name = row.__tablename__
        self.added[name] = self.added.get(name, 0) + 1
        return row

    async def get_or_add(self, stmt: Any, make: Any) -> Any:
        row = await self.first(stmt)
        if row is None:
            row = self.add(make())
            await self.session.flush()
        return row


async def seed(session: AsyncSession) -> dict[str, int]:
    """Add whatever demo data is missing. Returns {table: rows added}."""
    from api.core import clock

    s = Seeder(session)
    now, today = clock.now(), clock.today()

    # ---------------------------------------------------------------- users
    author = await s.get_or_add(
        select(User).where(User.email == email("content")),
        lambda: User(
            firebase_uid="demo-content",
            email=email("content"),
            display_name="BrAInBox content team",
            role=UserRole.ADMIN,
            email_verified=True,
        ),  # fmt: skip
    )
    students: dict[str, User] = {}
    for key, name, school, district, year_offset, active, days_ago, _mastery in STUDENTS:
        user = await s.get_or_add(
            select(User).where(User.email == email(key)),
            lambda key=key, name=name, active=active: User(
                firebase_uid=f"demo-{key}",
                email=email(key),
                display_name=name,
                role=UserRole.STUDENT,
                is_active=active,
                email_verified=True,
                created_at=now - timedelta(days=60),
            ),  # fmt: skip
        )
        students[key] = user
        await s.get_or_add(
            select(StudentProfile).where(StudentProfile.user_id == user.id),
            lambda user=user, school=school, district=district, year_offset=year_offset: (
                StudentProfile(
                    user_id=user.id,
                    school=school,
                    district=district,
                    exam_year=today.year + year_offset,
                    stream="bio_science",
                    subject="biology",
                    target_grade="A",
                )
            ),  # fmt: skip
        )
        for back in (days_ago, days_ago + 1, days_ago + 2):
            day = today - timedelta(days=back)
            await s.get_or_add(
                select(StudyActivity).where(
                    StudyActivity.user_id == user.id, StudyActivity.activity_date == day
                ),
                lambda user=user, day=day: StudyActivity(user_id=user.id, activity_date=day),
            )

    # ---------------------------------------------------------------- syllabus (only if missing)
    units: dict[int, Unit] = {}
    topics: dict[str, Topic] = {}
    for number, title, topic_rows in UNITS:
        unit = await s.get_or_add(
            select(Unit).where(Unit.number == number),
            lambda number=number, title=title: Unit(number=number, title=title, code=f"u{number}"),
        )
        units[number] = unit
        for order, (topic_number, topic_title) in enumerate(topic_rows, start=1):
            topics[topic_number] = await s.get_or_add(
                select(Topic).where(Topic.unit_id == unit.id, Topic.number == topic_number),
                lambda unit=unit, n=topic_number, t=topic_title, o=order: Topic(
                    unit_id=unit.id, number=n, title=t, order_index=o
                ),
            )
    for key, *_, mastery in STUDENTS:
        user = students[key]
        await s.get_or_add(
            select(UnitMastery).where(UnitMastery.user_id == user.id),
            lambda user=user, mastery=mastery: UnitMastery(
                user_id=user.id, unit_id=units[6].id, mastery=mastery, source="diagnostic"
            ),
        )

    # ---------------------------------------------------------------- community + moderation
    groups: dict[str, CommunityGroup] = {}
    for slug, name, moderator in GROUPS:
        group = await s.get_or_add(
            select(CommunityGroup).where(CommunityGroup.slug == slug),
            lambda slug=slug, name=name: CommunityGroup(
                name=name, slug=slug, created_by=author.id, is_private=False
            ),
        )
        groups[slug] = group
        for key in ("nethmi", "kavindu", "sanduni", "ishara"):
            role = "moderator" if key == moderator else "member"
            await s.get_or_add(
                select(GroupMember).where(
                    GroupMember.group_id == group.id, GroupMember.user_id == students[key].id
                ),
                lambda group=group, key=key, role=role: GroupMember(
                    group_id=group.id, user_id=students[key].id, role=role
                ),
            )
    genetics = groups["demo-unit-6-genetics"]
    spam = await s.get_or_add(
        select(Post).where(
            Post.author_id == students["kavindu"].id, Post.title == "Leaked 2026 papers"
        ),
        lambda: Post(
            group_id=genetics.id,
            author_id=students["kavindu"].id,
            title="Leaked 2026 papers",
            body="Join my WhatsApp for leaked papers 👉 bit.ly/...",
            moderation_status=ModerationStatus.FLAGGED,
            moderation_reason="Spam / external link",
            moderation_score=Decimal("0.960"),
        ),  # fmt: skip
    )
    question_post = await s.get_or_add(
        select(Post).where(
            Post.author_id == students["nethmi"].id, Post.title == "Dihybrid ratio?"
        ),
        lambda: Post(
            group_id=genetics.id,
            author_id=students["nethmi"].id,
            title="Dihybrid ratio?",
            body="Why is the F2 ratio 9:3:3:1?",
            moderation_status=ModerationStatus.APPROVED,
        ),  # fmt: skip
    )
    rude = await s.get_or_add(
        select(Reply).where(
            Reply.post_id == question_post.id, Reply.author_id == students["ruwan"].id
        ),
        lambda: Reply(
            post_id=question_post.id,
            author_id=students["ruwan"].id,
            body="Just copy the answer, studying is useless",
            moderation_reason="Academic integrity",
            moderation_score=Decimal("0.710"),
        ),  # fmt: skip
    )
    for reporter, target_type, target, reason in [
        ("nethmi", "post", spam, "spam"),
        ("sanduni", "post", spam, "spam"),
        ("ishara", "post", spam, "spam"),
        ("nethmi", "reply", rude, "other"),
    ]:
        await s.get_or_add(
            select(ContentReport).where(
                ContentReport.reporter_id == students[reporter].id,
                ContentReport.target_id == target.id,
            ),
            lambda reporter=reporter, t=target_type, target=target, reason=reason: ContentReport(
                reporter_id=students[reporter].id, target_type=t, target_id=target.id, reason=reason
            ),
        )

    # ---------------------------------------------------------------- visuals
    reported_visual = await s.get_or_add(
        select(Visual).where(
            Visual.created_by == author.id, Visual.title == "Nephron labelled diagram"
        ),
        lambda: Visual(
            topic_id=topics["5.4"].id,
            kind=VisualKind.DIAGRAM,
            title="Nephron labelled diagram",
            status=ContentStatus.APPROVED,
            mermaid_code='flowchart LR\n  A["Bowman\'s capsule"] --> B["PCT"] --> C["Loop of Henle"]',
            created_by=author.id,
            verified_by=author.id,
            verified_at=now,
        ),  # fmt: skip
    )
    await s.get_or_add(
        select(VisualReport).where(VisualReport.visual_id == reported_visual.id),
        lambda: VisualReport(
            visual_id=reported_visual.id,
            user_id=students["ishara"].id,
            reason="unclear",
            details="Labels overlap",
        ),  # fmt: skip
    )
    await s.get_or_add(
        select(Visual).where(
            Visual.created_by == students["nethmi"].id, Visual.title == "Meiosis stages"
        ),
        lambda: Visual(
            topic_id=topics["6.1"].id,
            kind=VisualKind.FLOWCHART,
            title="Meiosis stages",
            status=ContentStatus.DRAFT,
            is_ai_generated=True,
            safety_passed=True,
            mermaid_code="flowchart LR\n  P1[Prophase I] --> M1[Metaphase I] --> A1[Anaphase I]",
            prompt="Show the stages of meiosis",
            created_by=students["nethmi"].id,
            model="gemini-2.5-flash",
            prompt_version="visuals/decide_visual.v2",
        ),  # fmt: skip
    )

    # ---------------------------------------------------------------- notes
    for title, kind, topic, body in [
        ("Nephron structure & function", "short", "5.4",
         "## Overview\nThe nephron is the functional unit of the kidney.\n\n## Key regions\n"
         "- Bowman's capsule: pressure filtration\n- PCT: selective reabsorption\n"
         "- Loop of Henle: counter-current multiplier"),
        ("Dihybrid cross: worked examples", "full", "6.1",
         "A dihybrid cross follows two genes at once. With independent assortment the F2 ratio is 9:3:3:1."),
    ]:  # fmt: skip
        await s.get_or_add(
            select(Note).where(Note.created_by == author.id, Note.title == title),
            lambda title=title, kind=kind, topic=topic, body=body: Note(
                topic_id=topics[topic].id,
                title=title,
                note_type=kind,
                body_md=body,
                status=ContentStatus.PENDING_REVIEW,
                source=ContentSource.AI,
                created_by=author.id,
                model="gemini-2.5-flash",
                prompt_version=f"notes/{kind}.v2",
            ),  # fmt: skip
        )

    # ---------------------------------------------------------------- questions
    async def mcq(stem: str, topic: str, status: ContentStatus, source: str,
                  options: list[tuple[str, bool, str | None]], **extra: Any) -> Question:  # fmt: skip
        question = await s.first(
            select(Question).where(Question.created_by == author.id, Question.stem == stem)
        )
        if question is not None:
            return question
        question = s.add(
            Question(
                unit_id=topics[topic].unit_id,
                topic_id=topics[topic].id,
                question_type=QuestionType.MCQ,
                stem=stem,
                status=status,
                source=source,
                created_by=author.id,
                **extra,
            )  # fmt: skip
        )
        await session.flush()
        for label, (text, correct, wrong_idea) in zip("ABCDE", options, strict=False):
            idea = None
            if wrong_idea:
                idea = await s.get_or_add(
                    select(Misconception).where(
                        Misconception.created_by == author.id, Misconception.title == wrong_idea
                    ),
                    lambda wrong_idea=wrong_idea: Misconception(
                        title=wrong_idea, created_by=author.id
                    ),
                )
            s.add(MCQOption(question_id=question.id, label=label, text=text, is_correct=correct,
                            misconception_id=idea.id if idea else None))  # fmt: skip
        await session.flush()
        return question

    linked = [
        ("9:3:3:1", False, "Assumes independent assortment for linked genes"),
        ("Mostly parental types", True, None),
        ("1:1:1:1", False, "Confuses a test cross with an F2 cross"),
        ("3:1", False, "Treats two genes as one"),
        ("All recombinants", False, "Thinks crossing over always happens"),
    ]
    approved = [
        await mcq(
            f"Two linked genes are crossed (cross {n}). Which F2 result is expected?",
            "6.2",
            ContentStatus.APPROVED,
            "admin",
            linked,
            difficulty=Difficulty.HARD,
        )  # fmt: skip
        for n in range(1, 6)
    ]
    await mcq("Which enzyme property explains the effect of temperature on reaction rate?", "2.3",
              ContentStatus.APPROVED, "admin",
              [("Active site shape", True, None), ("Enzyme colour", False, "Thinks enzymes are pigments"),
               ("Substrate mass", False, "Confuses substrate with enzyme"),
               ("pH of water", False, "Mixes up pH and temperature"),
               ("Cell size", False, "Thinks rate depends on cell size")])  # fmt: skip
    ai_waiting = await mcq(
        "In the Krebs cycle, which molecule combines with acetyl CoA?", "2.3",
        ContentStatus.PENDING_REVIEW, "ai",
        [("Oxaloacetate", True, None), ("Pyruvate", False, None), ("Citrate", False, None),
         ("Glucose", False, None), ("NADH", False, None)],
        model="gemini-2.5-flash", prompt_version="questions/generate_mcq.v1",
        created_at=now - timedelta(hours=60),
    )  # fmt: skip
    await mcq("Which hormone increases water reabsorption in the collecting duct?", "5.4",
              ContentStatus.PENDING_REVIEW, "ai",
              [("ADH", True, None), ("Aldosterone", False, "Confuses ADH and aldosterone"),
               ("Insulin", False, "Mixes up endocrine roles"),
               ("Glucagon", False, "Mixes up endocrine roles"),
               ("Thyroxine", False, "Thinks metabolism hormones control water")])  # fmt: skip
    await s.get_or_add(
        select(QuestionReview).where(QuestionReview.question_id == ai_waiting.id),
        lambda: QuestionReview(
            question_id=ai_waiting.id,
            reviewer_type="ai",
            verdict="revise",
            checks={
                "single_correct_answer": True,
                "distractor_quality": {
                    "result": "review",
                    "note": "Glucose is too easy to rule out",
                },
                "syllabus_match": "pass",
                "duplicate_check": True,
            },
            model="gemini-2.5-flash",
            prompt_version="questions/review_mcq.v1",
        ),  # fmt: skip
    )
    for key in ("kavindu", "sanduni"):
        await s.get_or_add(
            select(QuestionReport).where(
                QuestionReport.question_id == ai_waiting.id,
                QuestionReport.user_id == students[key].id,
            ),
            lambda key=key: QuestionReport(
                question_id=ai_waiting.id, user_id=students[key].id, reason="wrong_answer"
            ),  # fmt: skip
        )
    await s.get_or_add(
        select(Question).where(Question.created_by == author.id, Question.source == "past_paper"),
        lambda: Question(
            unit_id=topics["6.1"].unit_id,
            topic_id=topics["6.1"].id,
            question_type=QuestionType.STRUCTURED,
            source="past_paper",
            year=2019,
            stem="Explain why the F2 ratio of a dihybrid cross is 9:3:3:1.",
            status=ContentStatus.APPROVED,
            created_by=author.id,
            marks=6,
        ),  # fmt: skip
    )

    # ---------------------------------------------------------------- a finished quiz today
    paper = await s.get_or_add(
        select(Paper).where(Paper.created_by == author.id, Paper.title == "Demo: linkage quiz"),
        lambda: Paper(
            title="Demo: linkage quiz",
            paper_type="quiz",
            created_by=author.id,
            status=ContentStatus.APPROVED,
        ),  # fmt: skip
    )
    for key in ("nethmi", "kavindu", "ishara"):
        attempt = await s.get_or_add(
            select(Attempt).where(
                Attempt.paper_id == paper.id, Attempt.user_id == students[key].id
            ),
            lambda key=key: Attempt(
                paper_id=paper.id,
                user_id=students[key].id,
                status="graded",
                started_at=now - timedelta(minutes=20),
                submitted_at=now,
            ),  # fmt: skip
        )
        for question in approved:
            options = (
                (
                    await session.execute(
                        select(MCQOption).where(MCQOption.question_id == question.id)
                    )
                )
                .scalars()
                .all()
            )
            wrong = next(o for o in options if o.label == "A")  # the most common wrong idea
            await s.get_or_add(
                select(Response).where(
                    Response.attempt_id == attempt.id, Response.question_id == question.id
                ),
                lambda attempt=attempt, question=question, wrong=wrong: Response(
                    attempt_id=attempt.id,
                    question_id=question.id,
                    selected_option_id=wrong.id,
                    is_correct=False,
                    marks_awarded=0.0,
                ),  # fmt: skip
            )

    # ---------------------------------------------------------------- past paper
    past = await s.get_or_add(
        select(PastPaper).where(PastPaper.uploaded_by == author.id, PastPaper.year == 2019),
        lambda: PastPaper(
            year=2019,
            paper_type="paper_2_structured",
            file_name="2019_P2.pdf",
            file_path="past_papers/demo-2019-p2.pdf",
            size_bytes=1,
            extraction_status="done",
            progress=1.0,
            uploaded_by=author.id,
            scheme_path="past_papers/demo-2019-p2-scheme.pdf",
        ),  # fmt: skip
    )
    for position, (label, marks, text, confidence, keywords) in enumerate(
        [
            ("Q1 (a)", 2, "Name the part of the nephron labelled X.", 0.97, ["nephron"]),
            ("Q1 (b)", 4, "Explain how glucose is reabsorbed in the proximal tubule.", 0.92,
             ["glucose", "reabsorbed", "proximal"]),
            ("Q3 (b)", 6, "Expla1n the c0unter-current mechan1sm.", 0.62, ["counter", "current"]),
        ],
        start=1,
    ):  # fmt: skip
        await s.get_or_add(
            select(PastPaperQuestion).where(
                PastPaperQuestion.past_paper_id == past.id, PastPaperQuestion.label == label
            ),
            lambda p=position, label=label, marks=marks, text=text, c=confidence, k=keywords: (
                PastPaperQuestion(
                    past_paper_id=past.id,
                    position=p,
                    label=label,
                    marks=marks,
                    text=text,
                    ocr_confidence=c,
                    suggested_keywords=k,
                    keywords=[],
                )
            ),  # fmt: skip
        )

    await session.commit()
    return s.added


async def clear(session: AsyncSession) -> int:
    """Remove the demo data (everything owned by a demo user). Returns how many users."""
    ids = list(
        (
            await session.execute(select(User.id).where(User.email.like(f"%@{DEMO_DOMAIN}")))
        ).scalars()
    )
    if not ids:
        return 0
    post_ids = select(Post.id).where(Post.author_id.in_(ids))
    for stmt in (
        delete(ContentReport).where(ContentReport.reporter_id.in_(ids)),
        delete(Reply).where(Reply.author_id.in_(ids)),
        delete(Reply).where(Reply.post_id.in_(post_ids)),
        delete(Post).where(Post.author_id.in_(ids)),
        delete(CommunityGroup).where(CommunityGroup.slug.like("demo-%")),
        delete(PastPaper).where(PastPaper.uploaded_by.in_(ids)),
        delete(Paper).where(Paper.created_by.in_(ids)),
        delete(Question).where(Question.created_by.in_(ids)),
        delete(Misconception).where(Misconception.created_by.in_(ids)),
        delete(Note).where(Note.created_by.in_(ids)),
        delete(Visual).where(Visual.created_by.in_(ids)),
        delete(User).where(User.id.in_(ids)),
    ):
        await session.execute(stmt)
    await session.commit()
    return len(ids)


def refuse_in_production() -> None:
    environment = get_shared_settings().ENVIRONMENT.lower()
    if environment in PRODUCTION:
        raise SystemExit(f"Refusing to run: ENVIRONMENT={environment}. Demo data is for dev only.")


async def _main(clear_only: bool) -> None:
    refuse_in_production()
    async with SessionLocal() as session:
        if clear_only:
            print(f"Removed the demo data of {await clear(session)} demo user(s).")
            return
        added = await seed(session)
    if not added:
        print("Demo data is already there - nothing to add.")
    for table, n in sorted(added.items()):
        print(f"  + {n:3} {table}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Demo data for the admin portal (dev only)")
    parser.add_argument("--clear", action="store_true", help="remove the demo data")
    asyncio.run(_main(parser.parse_args().clear))


if __name__ == "__main__":
    main()
