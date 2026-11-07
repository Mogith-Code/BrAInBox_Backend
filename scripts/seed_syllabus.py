"""Load data/syllabus/al_biology_syllabus.json into subjects, units, topics and concepts.

Safe to run many times: rows are matched by their public code ("biology", "u6", "bio-6.1",
"bio-6.1.1") and updated, never duplicated. Rows seeded before codes existed are matched by
unit number / topic number, so the old placeholder syllabus is upgraded in place.
Sub-topics are stored in the `concepts` table.

    python scripts/seed_syllabus.py
    python scripts/seed_syllabus.py --file data/syllabus/other.json
"""

import argparse
import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from shared.db.models import Concept, Subject, Topic, Unit
from shared.db.session import SessionLocal

DEFAULT_FILE = _bootstrap.REPO_ROOT / "data" / "syllabus" / "al_biology_syllabus.json"


@dataclass
class SeedCounts:
    units: int
    topics: int
    subtopics: int


def load_syllabus(path: Path) -> dict[str, Any]:
    """Read the syllabus JSON and check every code is unique (a duplicate would merge rows)."""
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    topic_codes = [t["code"] for u in data["units"] for t in u["topics"]]
    for label, codes in (
        ("unit id", [u["id"] for u in data["units"]]),
        ("topic code", topic_codes),
    ):
        duplicates = {c for c in codes if codes.count(c) > 1}
        if duplicates:
            raise ValueError(f"Duplicate {label}(s) in {path}: {', '.join(sorted(duplicates))}")
    return data


def count_syllabus(data: dict[str, Any]) -> SeedCounts:
    """How many units / topics / sub-topics the file holds."""
    topics = [t for u in data["units"] for t in u["topics"]]
    return SeedCounts(
        units=len(data["units"]),
        topics=len(topics),
        subtopics=sum(len(t["subtopics"]) for t in topics),
    )


def code_prefix(subject: dict[str, Any]) -> str:
    """Prefix of topic codes: "biology" -> "bio" (so topic 6.1 -> "bio-6.1")."""
    return str(subject.get("code_prefix") or subject["id"][:3])


async def seed_session(session: AsyncSession, data: dict[str, Any]) -> SeedCounts:
    """Upsert the whole syllabus in one session and commit. Returns the counts in the database."""
    subject_data = data["subject"]
    prefix = code_prefix(subject_data)

    subject = (
        await session.execute(select(Subject).where(Subject.code == subject_data["id"]))
    ).scalar_one_or_none()
    if subject is None:
        subject = Subject(code=subject_data["id"], name="", level="")
        session.add(subject)
    subject.name = subject_data["name"]
    subject.level = subject_data["level"]
    await session.flush()  # gives the subject its id

    # Load what exists once, then match in memory (about 300 rows in total).
    units = list((await session.execute(select(Unit))).scalars())
    units_by_code = {u.code: u for u in units if u.code}
    units_by_number = {u.number: u for u in units}
    topics = list((await session.execute(select(Topic))).scalars())
    topics_by_code = {t.code: t for t in topics if t.code}
    topics_by_number = {(t.unit_id, t.number): t for t in topics}
    concepts = list((await session.execute(select(Concept))).scalars())
    concepts_by_code = {c.code: c for c in concepts if c.code}
    concepts_by_name = {(c.topic_id, c.name): c for c in concepts}

    for unit_data in data["units"]:
        unit = units_by_code.get(unit_data["id"]) or units_by_number.get(unit_data["number"])
        if unit is None:
            unit = Unit(number=unit_data["number"], title="")
            session.add(unit)
        unit.subject_id = subject.id
        unit.code = unit_data["id"]
        unit.number = unit_data["number"]
        unit.title = unit_data["title"]
        unit.periods = unit_data.get("periods")
        unit.icon = unit_data.get("icon")
        await session.flush()  # gives a new unit its id

        for topic_order, topic_data in enumerate(unit_data["topics"], start=1):
            topic_code = f"{prefix}-{topic_data['code']}"
            topic = topics_by_code.get(topic_code) or topics_by_number.get(
                (unit.id, topic_data["code"])
            )
            if topic is None:
                topic = Topic(unit_id=unit.id, number=topic_data["code"], title="")
                session.add(topic)
            topic.unit_id = unit.id
            topic.code = topic_code
            topic.number = topic_data["code"]
            topic.title = topic_data["title"]
            topic.order_index = topic_order
            await session.flush()  # gives a new topic its id

            for concept_order, title in enumerate(topic_data["subtopics"], start=1):
                concept_code = f"{topic_code}.{concept_order}"
                concept = concepts_by_code.get(concept_code) or concepts_by_name.get(
                    (topic.id, title)
                )
                if concept is None:
                    concept = Concept(topic_id=topic.id, name=title)
                    session.add(concept)
                concept.topic_id = topic.id
                concept.code = concept_code
                concept.name = title
                concept.order_index = concept_order
        print(
            f"  unit {unit.number:>2}: {unit.title} ({len(unit_data['topics'])} topics, "
            f"{sum(len(t['subtopics']) for t in unit_data['topics'])} sub-topics)"
        )
    await session.commit()
    return await count_in_database(session, subject.id)


async def count_in_database(session: AsyncSession, subject_id: Any) -> SeedCounts:
    """Units / topics / concepts of one subject, as stored."""
    unit_ids = select(Unit.id).where(Unit.subject_id == subject_id)
    topic_ids = select(Topic.id).where(Topic.unit_id.in_(unit_ids))
    units = await session.scalar(
        select(func.count()).select_from(Unit).where(Unit.id.in_(unit_ids))
    )
    topics = await session.scalar(
        select(func.count()).select_from(Topic).where(Topic.id.in_(topic_ids))
    )
    subtopics = await session.scalar(
        select(func.count()).select_from(Concept).where(Concept.topic_id.in_(topic_ids))
    )
    return SeedCounts(units=units or 0, topics=topics or 0, subtopics=subtopics or 0)


async def seed(
    path: Path, session_factory: async_sessionmaker[AsyncSession] = SessionLocal
) -> SeedCounts:
    data = load_syllabus(path)
    async with session_factory() as session:
        counts = await seed_session(session, data)
    print(
        f"Seeded {data['subject']['name']} from {path}: "
        f"{counts.units} units, {counts.topics} topics, {counts.subtopics} sub-topics"
    )
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE)
    args = parser.parse_args()
    asyncio.run(seed(args.file))


if __name__ == "__main__":
    main()
