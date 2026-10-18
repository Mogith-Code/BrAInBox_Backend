"""POST /jobs/run -> run one AI job by its JobType.

The api creates the `ai_jobs` row and calls this endpoint (api/core/jobs.py). We only
compute and return the result; the api stores it on the job row.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter

from ai_service.pipelines.community import moderation, suggested_answer
from ai_service.pipelines.evaluation import ocr, scorer
from ai_service.pipelines.notes import generate_notes, short_notes
from ai_service.pipelines.questions import (
    generate_questions,
    mcq_mapping,
    paper_builder,
    quality_checks,
)
from ai_service.pipelines.recommendations import rank_resources
from ai_service.pipelines.summarization import summarize
from ai_service.pipelines.visuals import decide_visual
from ai_service.rag.ingestion import pipeline as rag_ingest
from ai_service.schemas.jobs import JobRunRequest, JobRunResponse
from shared.enums import JobType

router = APIRouter(prefix="/jobs", tags=["Jobs"])

PipelineFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

# One entry per JobType. Adding a JobType? Add its pipeline here (a test checks none is missing).
DISPATCH: dict[JobType, PipelineFn] = {
    JobType.SUMMARIZE_UPLOAD: summarize.run,
    JobType.GENERATE_NOTES: generate_notes.run,
    JobType.GENERATE_SHORT_NOTES: short_notes.run,
    JobType.GENERATE_VISUAL: decide_visual.run,
    JobType.GENERATE_QUESTIONS: generate_questions.run,
    JobType.REVIEW_QUESTIONS: quality_checks.run,
    JobType.MAP_MISCONCEPTIONS: mcq_mapping.run,
    JobType.BUILD_PAPER: paper_builder.run,
    JobType.EVALUATE_ANSWER: scorer.run,
    JobType.OCR_ANSWER: ocr.run,
    JobType.MODERATE_POST: moderation.run,
    JobType.SUGGEST_ANSWER: suggested_answer.run,
    JobType.RANK_RESOURCES: rank_resources.run,
    JobType.RAG_INGEST: rag_ingest.run_job,
}


@router.post("/run", response_model=JobRunResponse, summary="Run one AI job")
async def run_job(request: JobRunRequest) -> JobRunResponse:
    pipeline = DISPATCH[request.job_type]  # job_type is validated by Pydantic
    result = await pipeline(request.payload)
    return JobRunResponse(job_id=request.job_id, job_type=request.job_type, result=result)
