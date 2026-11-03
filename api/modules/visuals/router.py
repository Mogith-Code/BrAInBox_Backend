"""HTTP endpoints for the visuals module. Owner: Mogith.

Implemented (details in README.md):
    GET    /api/v1/topics/{topic_id}/visuals               Approved visuals + my own, newest first
    GET    /api/v1/visuals/{visual_id}                     One visual
    POST   /api/v1/visuals/generate                        Request a visual -> GENERATE_VISUAL job (202)
    POST   /api/v1/visuals/{visual_id}/report              Report a wrong visual (201)
    GET    /api/v1/files/visuals/{path}                    Dev only: PNGs kept in LOCAL_STORAGE_DIR

Rule: routers only validate input, check the role and call `service`. No SQL here.
"""

import uuid

from fastapi import APIRouter, BackgroundTasks, Request, status
from fastapi.responses import FileResponse

from api.core import storage
from api.core.ai_client import AIClientDep
from api.core.database import SessionDep
from api.core.errors import NotFoundError
from api.core.security import CurrentUserDep
from api.modules.visuals import service
from api.modules.visuals.schemas import (
    GenerateVisualIn,
    JobCreatedOut,
    ReportVisualIn,
    TopicVisualsOut,
    VisualOut,
    VisualReportOut,
)

router = APIRouter(tags=["Visuals"])


@router.get(
    "/topics/{topic_id}/visuals",
    response_model=TopicVisualsOut,
    summary="Visuals of a topic (approved + my own)",
)
async def topic_visuals(
    topic_id: uuid.UUID, request: Request, user: CurrentUserDep, session: SessionDep
) -> TopicVisualsOut:
    """Approved visuals, plus my own in any status except rejected / archived. Newest first.

    Errors: 401 not logged in · 404 `TOPIC_NOT_FOUND`."""
    return await service.list_topic_visuals(session, user, topic_id, str(request.base_url))


@router.post(
    "/visuals/generate",
    response_model=JobCreatedOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ask the AI for a visual (returns a job id, then poll GET /jobs/{job_id})",
)
async def generate_visual(
    req: GenerateVisualIn,
    user: CurrentUserDep,
    session: SessionDep,
    ai: AIClientDep,
    background_tasks: BackgroundTasks,
) -> JobCreatedOut:
    """202 means the request was **accepted**. Poll `GET /api/v1/jobs/{job_id}`: on success
    `result` = `{"visual_id": "..."}`, then load `GET /api/v1/visuals/{visual_id}`.

    Errors: 401 not logged in · 404 `TOPIC_NOT_FOUND` · 422 `VALIDATION_ERROR` (prompt not
    5-300 characters, unknown visual_type / style) · 429 `VISUAL_LIMIT_REACHED` (+ `retry_after`).
    A request that is not about Biology fails the job with `error_code` = `NOT_BIOLOGY`."""
    return await service.request_visual(session, user, req, ai, background_tasks)


@router.get("/visuals/{visual_id}", response_model=VisualOut, summary="One visual")
async def get_visual(
    visual_id: uuid.UUID, request: Request, user: CurrentUserDep, session: SessionDep
) -> VisualOut:
    """Errors: 401 not logged in · 404 `VISUAL_NOT_FOUND` (unknown, or another student's
    visual that is not approved)."""
    return await service.get_visual(session, user, visual_id, str(request.base_url))


@router.post(
    "/visuals/{visual_id}/report",
    response_model=VisualReportOut,
    status_code=status.HTTP_201_CREATED,
    summary="Report a wrong or unclear visual",
)
async def report_visual(
    visual_id: uuid.UUID, req: ReportVisualIn, user: CurrentUserDep, session: SessionDep
) -> VisualReportOut:
    """Errors: 401 not logged in · 404 `VISUAL_NOT_FOUND` · 409 `ALREADY_REPORTED` (my
    earlier report of this visual is still pending) · 422 `VALIDATION_ERROR`."""
    return await service.report_visual(session, user, visual_id, req)


@router.get(
    "/files/visuals/{path:path}",
    response_class=FileResponse,
    include_in_schema=False,  # dev helper, not part of the public API
)
async def dev_visual_file(path: str) -> FileResponse:
    """Dev only (no STORAGE_BUCKET): serve a stored visual PNG without login, like a signed URL.

    Only files under visuals/ are served; with a bucket (or in prod) this is always a 404.
    """
    file = storage.local_file(f"visuals/{path}")
    if file is None:
        raise NotFoundError("File not found", code="FILE_NOT_FOUND")
    return FileResponse(file, media_type="image/png")
