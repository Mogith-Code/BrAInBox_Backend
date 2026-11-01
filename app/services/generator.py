import json
import random
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import List, Tuple

from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from app.config import LLM_API_KEY, LLM_MODEL, LLM_FALLBACK_MODEL
from app.models.schemas import Question
from app.services.question_bank import get_questions_by_topic
from app.services.retriever import get_context, get_unit_chunks

client = genai.Client(api_key=LLM_API_KEY)
MAX_RETRIES = 2                       # retries for invalid AI output
RETRYABLE_CODES = {429, 500, 503, 504}
MODELS = [m for m in (LLM_MODEL, LLM_FALLBACK_MODEL) if m]
DEFAULT_UNIT = "Chemical and Cellular Basis of Life"

BATCH_SIZE = 5          # questions per LLM call (unit papers)
CHUNKS_PER_BATCH = 4    # syllabus chunks given to each LLM call
MAX_WORKERS = 4         # parallel LLM calls (use 2 if Gemini returns 429 often)

SPREAD_RULE = "\nSpread the questions over different Source blocks so that each question tests a different fact.\n"


def build_prompt(topic: str, n: int, examples: List[Question], chunks: List[dict]) -> str:
    context = "\n\n".join(
        f"[Source {i + 1}]\n{c['text']}" for i, c in enumerate(chunks)
    )

    example_block = ""
    if examples:
        example_json = json.dumps(
            [e.model_dump(exclude={"id", "year"}) for e in examples],
            indent=2,
            ensure_ascii=False,
        )
        example_block = (
            "\nExample questions (use for style and difficulty only):\n"
            f"{example_json}\n"
        )

    return f"""You are an examiner for the Sri Lankan G.C.E. Advanced Level Biology paper.
Write {n} NEW multiple-choice questions on the topic "{topic}".

Rules:
- Base every question ONLY on the context below. Do not use outside facts.
- If the context is not enough for {n} good questions, return fewer questions.
- Each question has exactly 5 options and exactly ONE clearly correct option.
- "correct_answer" must be copied exactly from one of the options.
- Every wrong option must be clearly false for an A/L student. No wrong option may be partly or conditionally true.
- Never mention "the text", "the context", "the passage" or "the source" in any question or option. Each question must read like a normal exam question.
- Avoid vague wording. Do NOT copy sentences from the context directly.
- Return ONLY a JSON array. Each item must have the keys:
  "topic", "unit", "question", "options", "correct_answer", "marks".

Context:
{context}
{example_block}"""


def call_llm(prompt: str):
    """Call the LLM with backoff. Tries each model; waits 1s, 2s, 4s, 8s."""
    last_error = None
    for attempt in range(4):
        for model in MODELS:
            try:
                return client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.7,
                    ),
                )
            except errors.APIError as e:
                if e.code not in RETRYABLE_CODES:
                    raise
                last_error = e
        time.sleep(2 ** attempt)
    raise last_error


def _run_generation(prompt: str, n: int, topic: str, unit: str) -> List[Question]:
    """Call the LLM, validate every MCQ, retry when the output is invalid."""
    last_error = None
    for _ in range(MAX_RETRIES + 1):
        response = call_llm(prompt)
        try:
            data = json.loads(response.text)
            questions = []
            for item in data:
                item["id"] = f"AI-{uuid.uuid4().hex[:8]}"
                item["topic"] = topic
                item["unit"] = unit
                questions.append(Question(**item))
            return questions[:n]
        except (json.JSONDecodeError, ValidationError, TypeError) as e:
            last_error = e

    raise RuntimeError(f"LLM output was invalid after retries: {last_error}")


# ---------------------------------------------------------------
# By topic (kept as it was)
# ---------------------------------------------------------------
def generate_mcqs(topic: str, n: int) -> List[Question]:
    chunks = get_context(topic, k=4)
    if not chunks:
        raise ValueError(f"No syllabus content found for topic '{topic}'")

    examples = get_questions_by_topic(topic, 3)   # may be empty, that is fine
    unit = chunks[0]["meta"].get("unit", DEFAULT_UNIT)
    prompt = build_prompt(topic, n, examples, chunks)
    return _run_generation(prompt, n, topic, unit)


def generate_paper(topics: List[str], total: int):
    """Split `total` questions across topics and generate MCQs for each."""
    base, extra = divmod(total, len(topics))
    questions: List[Question] = []
    warnings: List[str] = []

    for idx, topic in enumerate(topics):
        count = base + (1 if idx < extra else 0)
        if count == 0:
            continue
        try:
            questions.extend(generate_mcqs(topic, count))
        except Exception as e:
            warnings.append(f"{topic}: {e}")

    return questions, warnings


# ---------------------------------------------------------------
# By unit (new)
# ---------------------------------------------------------------
def _split(total: int, parts: int) -> List[int]:
    base, extra = divmod(total, parts)
    return [base + (1 if i < extra else 0) for i in range(parts)]


def _batch_sizes(n: int) -> List[int]:
    full, rest = divmod(n, BATCH_SIZE)
    return [BATCH_SIZE] * full + ([rest] if rest else [])


def generate_paper_by_units(units: List[int], total: int) -> Tuple[List[Question], List[str]]:
    """Split `total` questions across the units; every unit is covered by
    several small LLM calls, each using different random chunks of that unit."""
    warnings: List[str] = []
    jobs = []                                    # (label, unit_name, n, chunks)

    for unit_no, count in zip(units, _split(total, len(units))):
        if count == 0:
            continue

        chunks = get_unit_chunks(unit_no)
        if not chunks:
            warnings.append(f"Unit {unit_no}: no syllabus content found")
            continue

        random.shuffle(chunks)
        unit_name = chunks[0]["meta"].get("unit", f"Unit {unit_no}")
        label = f"Unit {unit_no}: {unit_name}"
        per_batch = min(CHUNKS_PER_BATCH, len(chunks))

        pos = 0
        for n in _batch_sizes(count):
            batch = [chunks[(pos + i) % len(chunks)] for i in range(per_batch)]
            pos += per_batch
            jobs.append((label, unit_name, n, batch))

    def run(job):
        label, unit_name, n, batch = job
        prompt = build_prompt(unit_name, n, [], batch) + SPREAD_RULE
        return _run_generation(prompt, n, label, unit_name)

    questions: List[Question] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = [pool.submit(run, job) for job in jobs]
        for job, future in zip(jobs, futures):
            try:
                questions.extend(future.result())
            except Exception as e:
                warnings.append(f"{job[0]}: {e}")

    return questions, warnings