import json
import random
from pathlib import Path
from typing import List

from app.models.schemas import Question

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "question_bank.json"


def load_questions() -> List[Question]:
    with open(DATA_FILE, encoding="utf-8") as f:
        raw = json.load(f)
    return [Question(**q) for q in raw]


def get_questions_by_topic(topic: str, n: int) -> List[Question]:
    matches = [q for q in load_questions() if q.topic.lower() == topic.lower()]
    random.shuffle(matches)
    return matches[:n]