"""Match answer sentences to marking points by meaning (embeddings + cosine similarity)."""

import math
import re
from dataclasses import dataclass

from ai_service.providers import get_embedder

# Sentence ends, line breaks and list bullets all start a new "sentence".
_SPLIT_RE = re.compile(r"(?<=[.!?;])\s+|\n+|\s*[••]\s*")
MIN_SENTENCE_CHARS = 8
MAX_SENTENCES = 120  # a very long answer is cut here (keeps one embedding batch)


def split_sentences(text: str) -> list[str]:
    """The answer as sentences. Very short fragments ("Yes.") are joined to the next one."""
    parts = [p.strip() for p in _SPLIT_RE.split(text) if p and p.strip()]
    sentences: list[str] = []
    carry = ""
    for part in parts:
        current = f"{carry} {part}".strip() if carry else part
        if len(current) < MIN_SENTENCE_CHARS:
            carry = current
            continue
        sentences.append(current)
        carry = ""
    if carry:
        if sentences:
            sentences[-1] = f"{sentences[-1]} {carry}"
        else:
            sentences.append(carry)
    return sentences[:MAX_SENTENCES]


def candidates(sentences: list[str]) -> list[tuple[str, int]]:
    """(text, index of its first sentence): every sentence, plus every pair of neighbours,
    because one marking point is often spread over two sentences."""
    out = [(s, i) for i, s in enumerate(sentences)]
    out += [(f"{sentences[i]} {sentences[i + 1]}", i) for i in range(len(sentences) - 1)]
    return out


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    if norm == 0:
        return 0.0
    return max(0.0, min(1.0, dot / norm))


@dataclass
class Match:
    similarity: float  # 0..1, best cosine similarity for this marking point
    evidence: str  # the part of the answer that matched best ("" when nothing was written)
    position: int  # index of that sentence in the answer (-1 when there is none)


async def best_matches(answer: str, point_texts: list[str]) -> list[Match]:
    """For every marking point: the most similar part of the answer."""
    parts = candidates(split_sentences(answer))
    if not parts or not point_texts:
        return [Match(0.0, "", -1) for _ in point_texts]
    embedder = get_embedder()
    answer_vectors = await embedder.embed([text for text, _ in parts], task="document")
    point_vectors = await embedder.embed(point_texts, task="query")
    matches = []
    for point_vector in point_vectors:
        scores = [cosine(point_vector, vector) for vector in answer_vectors]
        best = max(range(len(scores)), key=lambda i: scores[i])
        matches.append(Match(round(scores[best], 4), parts[best][0], parts[best][1]))
    return matches
