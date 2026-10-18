from typing import Dict, List, Optional

from app.models.schemas import (
    EvaluateRequest,
    EvaluateResponse,
    Question,
    QuestionResult,
    TopicScore,
)

LETTERS = "ABCDE"
WEAK_THRESHOLD = 60.0     # topics below this percent are marked weak


def option_from_letter(q: Question, letter: Optional[str]) -> Optional[str]:
    if not letter:
        return None
    first = letter.strip().upper()[:1]
    if not first:
        return None
    idx = LETTERS.find(first)
    if idx == -1 or idx >= len(q.options):
        return None
    return q.options[idx]


def evaluate_paper(questions: List[Question], req: EvaluateRequest) -> EvaluateResponse:
    chosen = {a.question_id: a.selected for a in req.answers}

    results: List[QuestionResult] = []
    topic_stats: Dict[str, List[int]] = {}      # topic -> [correct, total]
    answered = correct = marks_obtained = marks_total = 0

    for q in questions:
        selected = option_from_letter(q, chosen.get(q.id))
        is_correct = selected == q.correct_answer

        if selected is not None:
            answered += 1
        if is_correct:
            correct += 1
            marks_obtained += q.marks
        marks_total += q.marks

        stats = topic_stats.setdefault(q.topic, [0, 0])
        stats[1] += 1
        if is_correct:
            stats[0] += 1

        results.append(QuestionResult(
            question_id=q.id,
            topic=q.topic,
            question=q.question,
            selected_option=selected,
            correct_answer=q.correct_answer,
            is_correct=is_correct,
            marks_awarded=q.marks if is_correct else 0,
        ))

    by_topic = [
        TopicScore(topic=t, correct=c, total=n, percent=round(100 * c / n, 1))
        for t, (c, n) in topic_stats.items()
    ]
    weak_topics = [s.topic for s in by_topic if s.percent < WEAK_THRESHOLD]
    percent = round(100 * marks_obtained / marks_total, 1) if marks_total else 0.0

    return EvaluateResponse(
        paper_id=req.paper_id,
        total_questions=len(questions),
        answered=answered,
        correct=correct,
        marks_obtained=marks_obtained,
        marks_total=marks_total,
        percent=percent,
        by_topic=by_topic,
        weak_topics=weak_topics,
        results=results,
    )