import json
from typing import List

from app.models.schemas import QuestionResult
from app.services.generator import call_llm
from app.services.retriever import get_context


def add_explanations(results: List[QuestionResult]) -> None:
    """Adds a short AI explanation to every wrong or unanswered question."""
    wrong = [r for r in results if not r.is_correct]
    if not wrong:
        return

    blocks = []
    for r in wrong:
        chunks = get_context(r.question, k=2)
        context = "\n".join(c["text"] for c in chunks)
        blocks.append(
            f"question_id: {r.question_id}\n"
            f"Question: {r.question}\n"
            f"Correct answer: {r.correct_answer}\n"
            f"Student's answer: {r.selected_option or 'not answered'}\n"
            f"Context:\n{context}\n"
        )

    prompt = (
        "You are an A/L Biology teacher giving feedback to a student.\n"
        "For each item below, write 1 to 2 simple sentences that explain why the "
        "correct answer is right and, if the student chose an answer, why it is wrong. "
        "Use only the context given for that item. "
        "Do not mention \"the context\" or \"the text\".\n"
        "Return ONLY a JSON array of objects with the keys \"question_id\" and \"explanation\".\n\n"
        + "\n---\n".join(blocks)
    )

    try:
        data = json.loads(call_llm(prompt).text)
        by_id = {d["question_id"]: d["explanation"] for d in data}
    except Exception as e:
        print(f"Explanation step failed: {e}")
        return

    for r in wrong:
        r.explanation = by_id.get(r.question_id)