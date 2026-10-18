"""Load data/syllabus/biology_units.json into the units + topics tables.

Safe to run many times: existing units/topics (matched by number) are updated, not duplicated.

    python scripts/seed_syllabus.py
    python scripts/seed_syllabus.py --file data/syllabus/other.json
"""

import argparse
import asyncio
import json
from pathlib import Path

import _bootstrap  # noqa: F401
from sqlalchemy import select

from shared.db.models import Topic, Unit
from shared.db.session import SessionLocal

DEFAULT_FILE = _bootstrap.REPO_ROOT / "data" / "syllabus" / "biology_units.json"


async def seed(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    async with SessionLocal() as session:
        for unit_data in data["units"]:
            unit = (
                await session.execute(select(Unit).where(Unit.number == unit_data["number"]))
            ).scalar_one_or_none()
            if unit is None:
                unit = Unit(number=unit_data["number"], title=unit_data["title"])
                session.add(unit)
                await session.flush()  # gives the unit its id
            unit.title = unit_data["title"]
            unit.description = unit_data.get("description")
            # past-paper weight for spreading diagnostic questions (1.0 until real values: TBD)
            unit.exam_weight = float(unit_data.get("exam_weight", 1.0))

            for index, topic_data in enumerate(unit_data.get("topics", [])):
                topic = (
                    await session.execute(
                        select(Topic).where(
                            Topic.unit_id == unit.id, Topic.number == topic_data["number"]
                        )
                    )
                ).scalar_one_or_none()
                if topic is None:
                    topic = Topic(unit_id=unit.id, number=topic_data["number"], title="")
                    session.add(topic)
                topic.title = topic_data["title"]
                topic.description = topic_data.get("description")
                topic.order_index = index
            print(
                f"  unit {unit.number:>2}: {unit.title} ({len(unit_data.get('topics', []))} topics)"
            )
        await session.commit()
    print(f"Seeded {len(data['units'])} units from {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE)
    args = parser.parse_args()
    asyncio.run(seed(args.file))


if __name__ == "__main__":
    main()
