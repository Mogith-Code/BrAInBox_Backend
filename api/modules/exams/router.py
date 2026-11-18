"""HTTP endpoints for the exams module. Owner: Udith.

Implemented:
    GET    /api/v1/papers                                  Approved past papers (?year=&type=)
    GET    /api/v1/papers/{id}                             One paper's questions (?hide_outdated=)
    POST   /api/v1/papers/generate                         Model paper from a blueprint -> 202 + job
    POST   /api/v1/papers/generate-by-units                AI MCQ paper for units (synchronous)
    POST   /api/v1/papers/{id}/submit                      Mark answers (written ones in background)

Old URLs of Udith's standalone exam app (no /api/v1 prefix, hidden from /docs; mounted with
`legacy_router` in api/main.py). New code should use the /api/v1 routes above:
    POST   /exam/generate-paper           = POST /api/v1/papers/generate
    POST   /exam/generate-paper-by-units  = POST /api/v1/papers/generate-by-units
    POST   /exam/evaluate                 = POST /api/v1/papers/{paper_id}/submit (paper_id in the body)

Planned (details in README.md):
    POST   /api/v1/attempts                                Start an attempt
    GET    /api/v1/attempts/{id}                           Attempt with answers

Rule: routers only validate input, check the role and call `service`. No SQL here.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Query, status

from api.core.ai_client import AIClientDep
from api.core.database import SessionDep
from api.core.pagination import Page, PageParamsDep
from api.core.security import CurrentUserDep
from api.modules.exams import service
from api.modules.exams.schemas import (
    EvaluateResponse,
    LegacyEvaluateRequest,
    PaperBlueprint,
    PaperDetail,
    PaperGenerateRequest,
    PaperJobOut,
    PaperOut,
    PaperSummary,
    SubmitRequest,
    UnitPaperGenerateRequest,
)
from shared.enums import QuestionType

router = APIRouter(tags=["Exams"])


@router.get("/papers", response_model=Page[PaperSummary], summary="Approved past papers")
async def list_papers(
    user: CurrentUserDep,
    session: SessionDep,
    paging: PageParamsDep,
    year: Annotated[int | None, Query(ge=1990, le=2100)] = None,
    type: Annotated[  # noqa: A002 - the public query name
        QuestionType | None, Query(description="Papers with this type of question")
    ] = None,
) -> Page[PaperSummary]:
    """Newest year first. `outdated_count` = questions on a part of the syllabus that is no
    longer taught (see `is_outdated` on GET /papers/{id})."""
    return await service.list_papers(session, year=year, question_type=type, paging=paging)


@router.post(
    "/papers/generate",
    response_model=PaperJobOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Make a model paper from a blueprint (runs in the background)",
)
async def generate_paper(
    req: PaperBlueprint,
    user: CurrentUserDep,
    session: SessionDep,
    ai: AIClientDep,
    background_tasks: BackgroundTasks,
) -> PaperJobOut:
    """Unseen approved bank questions are used first; the AI only writes the gaps (MCQ,
    structured and essay), grounded in the approved syllabus sources. A generated question
    that fails the quality checks is regenerated once, then left out.

    Poll `GET /api/v1/jobs/{job_id}`; when `succeeded`, open `result.paper_id` with
    `GET /papers/{id}` (`result.warnings` says if the paper came out short).

    Errors: 404 `TOPIC_NOT_FOUND` / `UNIT_NOT_FOUND` · 422 `VALIDATION_ERROR` ·
    429 `DAILY_LIMIT_REACHED` (PAPERS_DAILY_LIMIT per 24 hours)."""
    return await service.start_model_paper(session, user, req, ai, background_tasks)


@router.post(
    "/papers/generate-by-units",
    response_model=PaperOut,
    response_model_exclude_none=True,
    summary="Generate an AI model paper from syllabus units",
)
async def generate_paper_by_units(
    req: UnitPaperGenerateRequest, user: CurrentUserDep, session: SessionDep, ai: AIClientDep
) -> PaperOut:
    """Generate a model paper by selecting 1..10 syllabus units. Questions are split evenly
    across the units and grounded in the syllabus. Counts towards PAPERS_DAILY_LIMIT
    (429 `DAILY_LIMIT_REACHED`)."""
    return await service.generate_paper_by_units(session, user, req, ai)


@router.get("/papers/{paper_id}", response_model=PaperDetail, summary="One paper's questions")
async def get_paper(
    paper_id: uuid.UUID,
    user: CurrentUserDep,
    session: SessionDep,
    hide_outdated: bool = False,
) -> PaperDetail:
    """An approved past paper, or one of my model papers. No answers. Every question has
    `is_outdated`; `hide_outdated=true` leaves those out (`hidden_outdated` says how many).

    Errors: 404 `PAPER_NOT_FOUND` (unknown, or another student's paper)."""
    return await service.get_paper_detail(session, user, paper_id, hide_outdated=hide_outdated)


@router.post(
    "/papers/{paper_id}/submit",
    response_model=EvaluateResponse,
    summary="Submit answers: marks, score per topic, weak topics and explanations",
)
async def submit_paper(
    paper_id: uuid.UUID,
    req: SubmitRequest,
    user: CurrentUserDep,
    session: SessionDep,
    ai: AIClientDep,
    background_tasks: BackgroundTasks,
) -> EvaluateResponse:
    """MCQ answers use letters ("A".."E"); a missing or invalid letter counts as not answered.
    Structured / essay answers go in `answer_text`: they are marked in the background
    (`written[].evaluation_id` -> `GET /evaluations/{id}`) and added to the attempt's score;
    `status` is "marking" until then."""
    return await service.submit_paper(session, user, paper_id, req, ai, background_tasks)


# --------------------------------------------------------------------------- old /exam/* URLs
legacy_router = APIRouter(prefix="/exam", tags=["Exams (old URLs)"])


@legacy_router.post(
    "/generate-paper",
    response_model=PaperOut,
    response_model_exclude_none=True,
    include_in_schema=False,
    deprecated=True,
)
async def legacy_generate_paper(
    req: PaperGenerateRequest, user: CurrentUserDep, session: SessionDep, ai: AIClientDep
) -> PaperOut:
    """Old URL of POST /api/v1/papers/generate."""
    return await service.generate_paper(session, user, req, ai)


@legacy_router.post(
    "/generate-paper-by-units",
    response_model=PaperOut,
    response_model_exclude_none=True,
    include_in_schema=False,
    deprecated=True,
)
async def legacy_generate_paper_by_units(
    req: UnitPaperGenerateRequest, user: CurrentUserDep, session: SessionDep, ai: AIClientDep
) -> PaperOut:
    """Old URL of POST /api/v1/papers/generate-by-units."""
    return await service.generate_paper_by_units(session, user, req, ai)


@legacy_router.post(
    "/evaluate", response_model=EvaluateResponse, include_in_schema=False, deprecated=True
)
async def legacy_evaluate(
    req: LegacyEvaluateRequest,
    user: CurrentUserDep,
    session: SessionDep,
    ai: AIClientDep,
    background_tasks: BackgroundTasks,
) -> EvaluateResponse:
    """Old URL of POST /api/v1/papers/{paper_id}/submit."""
    submit = SubmitRequest(answers=req.answers, explain=req.explain)
    return await service.submit_paper(session, user, req.paper_id, submit, ai, background_tasks)
