"""Propose the misconception behind every wrong option of an MCQ.

Job type: MAP_MISCONCEPTIONS (dispatched by ai_service/routes/jobs.py)

Payload:
    {
      "question": {"id", "question", "options": [{"label": "A", "text": "...", "is_correct": false}]},
      "misconceptions": [{"id": "<uuid>", "title": "..."}]      # the ones already in the bank
    }
Result:
    {"mappings": [{"option_label": "C", "misconception_id": "<uuid>" | null,
                   "new_misconception_title": "..." | null, "similarity": 0.91}]}

The LLM names the misconception in its own words. If that is close in meaning to one we already
have (cosine similarity >= MISCONCEPTION_REUSE_SIMILARITY), the existing one is reused, so the
bank does not fill up with ten wordings of the same idea. An admin confirms every proposal in
the MCQ mapping editor; nothing here is saved as approved.
"""

import json
from typing import Any

from ai_service.config import get_settings
from ai_service.pipelines.evaluation.semantic_match import cosine
from ai_service.prompts import prompt_id, render_prompt
from ai_service.providers import get_embedder, get_llm
from ai_service.schemas.llm_outputs import MisconceptionMappingSet

PROMPT_NAME = "questions/map_misconceptions"
PROMPT_VERSION = 1
PROMPT_ID = prompt_id(PROMPT_NAME, PROMPT_VERSION)


async def reuse_existing(
    titles: list[str], known: list[dict[str, Any]]
) -> list[tuple[str | None, float]]:
    """For each proposed title: (id of a known misconception that means the same, similarity)."""
    if not titles or not known:
        return [(None, 0.0) for _ in titles]
    threshold = get_settings().MISCONCEPTION_REUSE_SIMILARITY
    embedder = get_embedder()
    new_vectors = await embedder.embed(titles)
    known_vectors = await embedder.embed([str(m["title"]) for m in known])
    out: list[tuple[str | None, float]] = []
    for vector in new_vectors:
        scores = [cosine(vector, other) for other in known_vectors]
        best = max(range(len(scores)), key=lambda i: scores[i])
        match = str(known[best]["id"]) if scores[best] >= threshold else None
        out.append((match, round(scores[best], 3)))
    return out


async def run(payload: dict[str, Any]) -> dict[str, Any]:
    question = payload["question"]
    known = list(payload.get("misconceptions") or [])
    known_ids = {str(m["id"]) for m in known}
    wrong_labels = {o["label"] for o in question.get("options", []) if not o.get("is_correct")}

    prompt = render_prompt(
        PROMPT_NAME,
        PROMPT_VERSION,
        question_json=json.dumps(question, ensure_ascii=False, indent=2),
        misconceptions=known,
    )
    reply = await get_llm().generate_json(prompt, MisconceptionMappingSet, prompt_name=PROMPT_ID)

    proposals = [m for m in reply.mappings if m.option_label in wrong_labels]
    # Titles the LLM invented: check whether we already have the same idea under other words.
    fresh = [
        m
        for m in proposals
        if (m.misconception_id not in known_ids) and (m.new_misconception_title or "").strip()
    ]
    reused = await reuse_existing([str(m.new_misconception_title) for m in fresh], known)
    by_label = {m.option_label: match for m, match in zip(fresh, reused, strict=True)}

    mappings = []
    for m in proposals:
        if m.misconception_id in known_ids:
            mappings.append(
                {
                    "option_label": m.option_label,
                    "misconception_id": m.misconception_id,
                    "new_misconception_title": None,
                    "similarity": 1.0,
                }
            )
            continue
        match_id, similarity = by_label.get(m.option_label, (None, 0.0))
        title = (m.new_misconception_title or "").strip() or None
        mappings.append(
            {
                "option_label": m.option_label,
                "misconception_id": match_id,
                "new_misconception_title": None if match_id else title,
                "similarity": similarity,
            }
        )
    return {"mappings": mappings, "prompt_version": PROMPT_ID}
