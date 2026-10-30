"""pgvector: a cosine-distance query returns the nearest concept first."""

import uuid

import pytest
from sqlalchemy import select

from shared.db.models import Concept, Topic, Unit
from tests.db.conftest import vector

pytestmark = pytest.mark.db


async def test_nearest_concept_comes_first(session):
    unit = Unit(number=900_000 + uuid.uuid4().int % 99_999, title="Vector test unit")
    session.add(unit)
    await session.flush()
    topic = Topic(unit_id=unit.id, number="V.1", title="Vector test topic")
    session.add(topic)
    await session.flush()

    near = Concept(topic_id=topic.id, name="near", embedding=vector(1.0, 0.0, 0.0))
    middle = Concept(topic_id=topic.id, name="middle", embedding=vector(0.7, 0.7, 0.0))
    far = Concept(topic_id=topic.id, name="far", embedding=vector(0.0, 0.0, 1.0))
    session.add_all([far, near, middle])
    await session.flush()

    query = vector(0.9, 0.1, 0.0)
    result = await session.execute(
        select(Concept.name)
        .where(Concept.topic_id == topic.id)
        .order_by(Concept.embedding.cosine_distance(query))  # SQL: embedding <=> :q
    )
    assert list(result.scalars()) == ["near", "middle", "far"]
