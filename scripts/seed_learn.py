"""Seed the Learn tab. Safe to run many times (rows are matched and updated, never duplicated).

    python scripts/seed_learn.py

What it loads:
  * subjects: Biology (available, syllabus 2025), Chemistry and Physics (available=false)
  * the 10 Biology units and their 98 topics from data/syllabus/learn_biology_2025.json.
    Topics are matched by code ("bio-6.1") or unit + number, so ids (and everything linked to
    them) are kept; their title, order and syllabus_version are updated. Topics of a Biology
    unit that are NOT in the file are marked is_outdated (never deleted).
  * "Mendelian inheritance" (bio-6.1): an official full + short note (every block type),
    1 diagram (data/seed/learn/dihybrid_punnett.png) and 2 sample videos
    (data/seed/learn/mendelian_inheritance.json)

Run it AFTER `alembic upgrade head`. scripts/seed_syllabus.py loads the older 64-topic list
(with sub-topics); run this one after it so the Learn titles win.
"""

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import storage
from shared.db.models import Note, Resource, Subject, Topic, Unit, Visual
from shared.db.session import SessionLocal
from shared.enums import ContentSource, ContentStatus, VisualKind
from shared.learn_blocks import parse_blocks, read_minutes, to_markdown

ROOT = _bootstrap.REPO_ROOT
SYLLABUS_FILE = ROOT / "data" / "syllabus" / "learn_biology_2025.json"
SAMPLE_FILE = ROOT / "data" / "seed" / "learn" / "mendelian_inheritance.json"
TOPIC_PREFIX = "bio"


@dataclass
class LearnCounts:
    subjects: int
    units: int
    topics: int  # current Biology topics
    notes: int  # official notes of the sample topic
    diagrams: int
    videos: int


def load_json(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


# --------------------------------------------------------------------------- syllabus


async def seed_syllabus(session: AsyncSession, data: dict[str, Any]) -> Subject:
    biology: Subject | None = None
    for s in data["subjects"]:
        subject = (
            await session.execute(select(Subject).where(Subject.code == s["code"]))
        ).scalar_one_or_none()
        if subject is None:
            subject = Subject(code=s["code"], name=s["name"], level=s["level"])
            session.add(subject)
        subject.name = s["name"]
        subject.level = s["level"]
        subject.available = s["available"]
        subject.syllabus_version = s["syllabus_version"]
        if s["code"] == "biology":
            biology = subject
    assert biology is not None, "the file must contain the biology subject"
    await session.flush()

    version = data["syllabus_version"]
    units = list((await session.execute(select(Unit))).scalars())
    units_by_code = {u.code: u for u in units if u.code}
    units_by_number = {u.number: u for u in units}
    topics = list((await session.execute(select(Topic))).scalars())
    topics_by_code = {t.code: t for t in topics if t.code}
    topics_by_number = {(t.unit_id, t.number): t for t in topics}

    for u in data["units"]:
        unit = units_by_code.get(u["code"]) or units_by_number.get(u["number"])
        if unit is None:
            unit = Unit(number=u["number"], title=u["title"])
            session.add(unit)
        unit.subject_id = biology.id
        unit.code = u["code"]
        unit.number = u["number"]
        unit.title = u["title"]
        unit.icon = u["icon"]
        unit.is_outdated = False
        await session.flush()

        keep: set[Any] = set()
        for order, t in enumerate(u["topics"], start=1):
            code = f"{TOPIC_PREFIX}-{t['number']}"
            topic = topics_by_code.get(code) or topics_by_number.get((unit.id, t["number"]))
            if topic is None:
                topic = Topic(unit_id=unit.id, number=t["number"], title=t["title"])
                session.add(topic)
            topic.unit_id = unit.id
            topic.code = code
            topic.number = t["number"]
            topic.title = t["title"]
            topic.order_index = order
            topic.syllabus_version = version
            topic.is_outdated = False
            await session.flush()
            keep.add(topic.id)

        # Topics of this unit that are not in the 2025 list: keep them, but mark outdated.
        for old in (await session.execute(select(Topic).where(Topic.unit_id == unit.id))).scalars():
            if old.id not in keep:
                old.is_outdated = True
        print(f"  unit {unit.number:>2}: {unit.title} ({len(u['topics'])} topics)")
    return biology


# --------------------------------------------------------------------------- sample topic


def _diagram_path(topic: Topic, name: str) -> str:
    return f"visuals/{topic.id}/{name}"


def _diagram_url(path: str) -> str:
    """URL for the note's image block. Dev (no bucket): relative to the API base URL."""
    if storage.uses_local_files():
        return f"/api/v1/files/{path}"
    minutes = 7 * 24 * 60  # Storage signed URLs last 7 days at most: re-run the seed to renew
    return storage.generate_signed_url(path, minutes)


async def seed_sample_topic(session: AsyncSession, sample: dict[str, Any]) -> Topic:
    topic = (
        await session.execute(select(Topic).where(Topic.code == sample["topic_code"]))
    ).scalar_one()

    # Diagram: copy the PNG to storage, then one approved visual row.
    d = sample["diagram"]
    path = _diagram_path(topic, d["storage_name"])
    storage.upload_bytes(path, (ROOT / d["file"]).read_bytes(), "image/png")
    visual = (
        await session.execute(
            select(Visual).where(Visual.topic_id == topic.id, Visual.image_path == path)
        )
    ).scalar_one_or_none()
    if visual is None:
        visual = Visual(topic_id=topic.id, kind=VisualKind.ILLUSTRATION, title=d["title"])
        session.add(visual)
    visual.title = d["title"]
    visual.alt_text = d["caption"]
    visual.image_path = path
    visual.width, visual.height = 790, 880
    visual.is_ai_generated = False
    visual.status = ContentStatus.APPROVED
    visual.order_index = d["order"]

    # Official notes (user_id NULL, approved). Matched by topic + type.
    image_url = _diagram_url(path)
    for note_type, n in sample["notes"].items():
        raw = json.loads(json.dumps(n["blocks"]).replace("{diagram_url}", image_url))
        blocks = parse_blocks(raw)
        note = (
            await session.execute(
                select(Note).where(
                    Note.topic_id == topic.id,
                    Note.note_type == note_type,
                    Note.user_id.is_(None),
                    Note.concept_id.is_(None),
                    Note.status == ContentStatus.APPROVED,
                )
            )
        ).scalar_one_or_none()
        if note is None:
            note = Note(topic_id=topic.id, note_type=note_type, title=n["title"], body_md="")
            session.add(note)
        note.title = n["title"]
        note.blocks = blocks
        note.body_md = to_markdown(blocks)
        note.depth = n.get("depth")
        note.read_minutes = read_minutes(blocks)
        note.status = ContentStatus.APPROVED
        note.source = ContentSource.MANUAL

    # Sample videos, matched by provider + external id.
    for v in sample["videos"]:
        video = (
            await session.execute(
                select(Resource).where(
                    Resource.provider == "internal", Resource.external_id == v["external_id"]
                )
            )
        ).scalar_one_or_none()
        if video is None:
            video = Resource(
                provider="internal",
                external_id=v["external_id"],
                title="",
                url="",
                resource_type="video",
            )
            session.add(video)
        video.title = v["title"]
        video.url = v["url"]
        video.thumbnail_url = v["thumbnail_url"]
        video.duration_seconds = v["duration_seconds"]
        video.channel = v["channel"]
        video.resource_type = "video"
        video.topic_id = topic.id
        video.status = ContentStatus.APPROVED
        video.order_index = v["order"]
    return topic


# --------------------------------------------------------------------------- run


async def counts(session: AsyncSession, biology: Subject, topic: Topic) -> LearnCounts:
    async def count(stmt: Any) -> int:
        return int((await session.execute(stmt)).scalar_one())

    return LearnCounts(
        subjects=await count(select(func.count(Subject.id))),
        units=await count(select(func.count(Unit.id)).where(Unit.subject_id == biology.id)),
        topics=await count(
            select(func.count(Topic.id))
            .join(Unit, Unit.id == Topic.unit_id)
            .where(Unit.subject_id == biology.id, Topic.is_outdated.is_(False))
        ),
        notes=await count(
            select(func.count(Note.id)).where(Note.topic_id == topic.id, Note.user_id.is_(None))
        ),
        diagrams=await count(select(func.count(Visual.id)).where(Visual.topic_id == topic.id)),
        videos=await count(select(func.count(Resource.id)).where(Resource.topic_id == topic.id)),
    )


async def seed(session_factory: Any = SessionLocal) -> LearnCounts:
    async with session_factory() as session:
        biology = await seed_syllabus(session, load_json(SYLLABUS_FILE))
        topic = await seed_sample_topic(session, load_json(SAMPLE_FILE))
        await session.commit()
        return await counts(session, biology, topic)


def main() -> None:
    print("Seeding the Learn tab...")
    result = asyncio.run(seed())
    print(
        f"Done: {result.subjects} subjects, {result.units} Biology units, {result.topics} topics; "
        f"'Mendelian inheritance' has {result.notes} notes, {result.diagrams} diagram(s), "
        f"{result.videos} videos."
    )


if __name__ == "__main__":
    main()
