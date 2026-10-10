import uuid
from typing import List, Optional

import psycopg
from psycopg.types.json import Jsonb

from app.config import DATABASE_URL
from app.models.schemas import Question


def _connect():
    conn = psycopg.connect(DATABASE_URL)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS papers (
            paper_id   TEXT PRIMARY KEY,
            questions  JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    return conn


def save_paper(questions: List[Question]) -> str:
    paper_id = f"PAPER-{uuid.uuid4().hex[:8]}"
    data = [q.model_dump() for q in questions]
    with _connect() as conn:
        conn.execute(
            "INSERT INTO papers (paper_id, questions) VALUES (%s, %s)",
            (paper_id, Jsonb(data)),
        )
    return paper_id


def get_paper(paper_id: str) -> Optional[List[Question]]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT questions FROM papers WHERE paper_id = %s", (paper_id,)
        ).fetchone()
    if row is None:
        return None
    return [Question(**q) for q in row[0]]