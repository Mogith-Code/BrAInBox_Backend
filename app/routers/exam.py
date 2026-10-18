from fastapi import APIRouter, HTTPException

from app.models.schemas import (
    EvaluateRequest,
    EvaluateResponse,
    ExamRequest,
    ExamResponse,
    PaperRequest,
    PaperResponse,
)
from app.services.evaluator import evaluate_paper
from app.services.generator import generate_mcqs, generate_paper
from app.services.paper_store import get_paper, save_paper
from app.services.question_bank import get_questions_by_topic
from app.config import DEBUG_SHOW_ANSWERS
from app.models.schemas import Question, StudentQuestion
from app.services.explainer import add_explanations

router = APIRouter(prefix="/exam", tags=["Exam"])

def to_student_view(q: Question) -> StudentQuestion:
    return StudentQuestion(
        id=q.id,
        topic=q.topic,
        unit=q.unit,
        question=q.question,
        options=q.options,
        marks=q.marks,
        correct_answer=q.correct_answer if DEBUG_SHOW_ANSWERS else None,
    )


@router.post("/generate", response_model=ExamResponse)
def generate_exam(req: ExamRequest):
    questions = get_questions_by_topic(req.topic, req.num_questions)
    if not questions:
        raise HTTPException(status_code=404, detail=f"No questions found for topic '{req.topic}'")
    return ExamResponse(subject=req.subject, topic=req.topic, questions=questions)


@router.post("/generate-ai", response_model=ExamResponse)
def generate_ai_exam(req: ExamRequest):
    try:
        questions = generate_mcqs(req.topic, req.num_questions)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI generation failed: {e}")
    return ExamResponse(subject=req.subject, topic=req.topic, questions=questions)


@router.post("/generate-paper", response_model=PaperResponse, response_model_exclude_none=True)
def generate_paper_endpoint(req: PaperRequest):
    questions, warnings = generate_paper(req.topics, req.num_questions)
    if not questions:
        raise HTTPException(status_code=502, detail=f"Could not generate any questions. {warnings}")
    paper_id = save_paper(questions)           # full questions (with answers) saved server-side
    return PaperResponse(
        paper_id=paper_id,
        subject=req.subject,
        topics=req.topics,
        total_questions=len(questions),
        questions=[to_student_view(q) for q in questions],
        warnings=warnings,
    )


@router.post("/evaluate", response_model=EvaluateResponse)
def evaluate_answers(req: EvaluateRequest):
    questions = get_paper(req.paper_id)
    if questions is None:
        raise HTTPException(status_code=404, detail=f"Paper '{req.paper_id}' not found")
    result = evaluate_paper(questions, req)
    if req.explain:
        add_explanations(result.results)
    return result