import json
import time
import uuid
from typing import List

from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from app.config import LLM_API_KEY, LLM_MODEL, LLM_FALLBACK_MODEL
from app.models.schemas import Question
from app.services.question_bank import get_questions_by_topic
from app.services.retriever import get_context

client = genai.Client(api_key=LLM_API_KEY)
MAX_RETRIES = 2                       # retries for invalid AI output
RETRYABLE_CODES = {429, 500, 503, 504}
MODELS = [m for m in (LLM_MODEL, LLM_FALLBACK_MODEL) if m]
DEFAULT_UNIT = "Chemical and Cellular Basis of Life"


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
- Avoid vague wording. Do NOT copy sentences from the context directly.
- Every wrong option must be clearly incorrect according to the context. No wrong option may also be partly correct.
- Never mention "the context", "the text", "the passage" or "the source" in a question or option. Each question must read like a normal exam question.
- Make the questions different from each other: cover different facts from the context.
- Never mention "the text", "the context", "the passage" or "the source" in any question or option. Each question must read like a normal exam question.
- Do not use a wrong option that is partly or conditionally true. Every wrong option must be clearly false for an A/L student.
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
    if last_error is not None:
        raise last_error
    raise RuntimeError("All LLM retry attempts failed")


def generate_mcqs(topic: str, n: int) -> List[Question]:
    chunks = get_context(topic, k=6)
    if not chunks:
        raise ValueError(f"No syllabus content found for topic '{topic}'")

    examples = get_questions_by_topic(topic, 3)   # may be empty, that is fine
    unit = chunks[0]["meta"].get("unit", DEFAULT_UNIT)

    prompt = build_prompt(topic, n, examples, chunks)
    last_error = None

    for _ in range(MAX_RETRIES + 1):
        response = call_llm(prompt)
        try:
            if not response.text:
                raise ValueError("Empty response text from LLM")
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