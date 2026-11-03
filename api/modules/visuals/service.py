"""Business logic for the visuals module. Owner: Mogith.

Generating a visual (POST /visuals/generate):
  1. Check the topic and the daily limit (VISUALS_DAILY_LIMIT per student per 24 hours).
  2. Create the `visuals` row first (status draft, is_ai_generated) and a GENERATE_VISUAL job
     whose payload carries the row's id.
  3. After the response, run the job (ai_service/pipelines/visuals/decide_visual.py) and save
     what it made on the row in the same commit as "succeeded" (core/jobs on_success).
  4. The app polls GET /jobs/{job_id}; on success `result` = {"visual_id": "..."}.

Who sees what: approved visuals are for everyone. A student also sees their own visuals
(any status except rejected / archived). Admins approve visuals in content review.

Rules:
  * SQL lives in `repository.py`, not here.
  * To use another module, call ITS service (e.g. `from api.modules.syllabus import service`),
    never its repository.
  * AI work goes through `api.core.ai_client` / `api.core.jobs`, never directly to a provider.
"""

import logging
import math
import uuid
from datetime import timedelta
from typing import Any

from fastapi import BackgroundTasks
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import clock, jobs, storage
from api.core.ai_client import AIClient
from api.core.config import get_settings
from api.core.errors import ConflictError, NotFoundError, TooManyRequestsError
from api.core.security import CurrentUser
from api.modules.syllabus import service as syllabus_service
from api.modules.visuals import repository
from api.modules.visuals.schemas import (
    GenerateVisualIn,
    JobCreatedOut,
    ReportVisualIn,
    TopicVisualsOut,
    VisualLabelOut,
    VisualOut,
    VisualReportAdminOut,
    VisualReportOut,
)
from shared.db.models import AIJob, Visual, VisualReport
from shared.db.session import SessionLocal
from shared.enums import (
    ContentStatus,
    JobStatus,
    JobType,
    ModerationStatus,
    VisualKind,
    VisualType,
)

logger = logging.getLogger(__name__)

LIMIT_WINDOW = timedelta(hours=24)
# Kind saved on the draft row until the AI decides (the column cannot be empty).
FIRST_GUESS_KIND = {
    VisualType.PROCESS: VisualKind.FLOWCHART,
    VisualType.COMPARISON: VisualKind.TABLE,
    VisualType.STRUCTURE: VisualKind.DIAGRAM,
}
NOT_BIOLOGY_CODE = "NOT_BIOLOGY"  # ai_service/pipelines/visuals/decide_visual.py


# --------------------------------------------------------------------------- responses


def _labels(raw: list[Any]) -> list[VisualLabelOut]:
    """Labels from the JSONB column. A broken entry is skipped instead of failing the page."""
    labels = []
    for item in raw or []:
        try:
            labels.append(VisualLabelOut.model_validate(item))
        except ValueError:
            logger.warning("Skipping a bad label: %r", item)
    return labels


def visual_out(visual: Visual, image_url: str | None) -> VisualOut:
    """Build the API response. Pure function: no database, no storage."""
    return VisualOut(
        id=visual.id,
        title=visual.title,
        topic_id=visual.topic_id,
        concept_id=visual.concept_id,
        kind=visual.kind,
        image_url=image_url,
        mermaid_code=visual.mermaid_code,
        alt_text=visual.alt_text,
        labels=_labels(visual.labels),
        style=visual.style,
        width=visual.width,
        height=visual.height,
        is_ai_generated=visual.is_ai_generated,
        is_verified=visual.verified_by is not None,
        created_at=visual.created_at,
    )


async def _out(visual: Visual, base_url: str) -> VisualOut:
    return visual_out(visual, await storage.public_image_url(visual.image_path, base_url))


def can_see(visual: Visual, user: CurrentUser) -> bool:
    """Same rule as repository.visible_to, for one row (admins see every visual)."""
    if user.is_admin or visual.status == ContentStatus.APPROVED:
        return True
    return visual.created_by == user.id and visual.status not in repository.HIDDEN_OWN_STATUSES


async def _visible_visual(session: AsyncSession, user: CurrentUser, visual_id: uuid.UUID) -> Visual:
    visual = await repository.get_visual(session, visual_id)
    if visual is None or not can_see(visual, user):
        # Someone else's draft is "not found" too, so its existence is not leaked.
        raise NotFoundError(f"Visual '{visual_id}' not found", code="VISUAL_NOT_FOUND")
    return visual


# --------------------------------------------------------------------------- read


async def list_topic_visuals(
    session: AsyncSession, user: CurrentUser, topic_id: uuid.UUID, base_url: str
) -> TopicVisualsOut:
    """The topic header + approved visuals + this student's own. 404 TOPIC_NOT_FOUND."""
    [topic] = await syllabus_service.get_topics(session, [topic_id])
    visuals = await repository.list_topic_visuals(session, topic_id, user.id)
    return TopicVisualsOut(
        topic_id=topic.id,
        topic_title=topic.title,
        unit_code=str(topic.unit_number) if topic.unit_number else None,
        unit_title=topic.unit_title,
        visuals=[await _out(v, base_url) for v in visuals],
    )


async def get_visual(
    session: AsyncSession, user: CurrentUser, visual_id: uuid.UUID, base_url: str
) -> VisualOut:
    return await _out(await _visible_visual(session, user, visual_id), base_url)


# --------------------------------------------------------------------------- generate


async def check_daily_limit(session: AsyncSession, user: CurrentUser) -> None:
    """429 VISUAL_LIMIT_REACHED (with retry_after seconds) when the student used them all."""
    limit = get_settings().VISUALS_DAILY_LIMIT
    now = clock.now()
    count, oldest = await repository.recent_requests(session, user.id, now - LIMIT_WINDOW)
    if count < limit:
        return
    # A place frees up when the oldest request in the window is 24 hours old.
    free_at = (oldest or now) + LIMIT_WINDOW
    retry_after = max(1, math.ceil((free_at - now).total_seconds()))
    raise TooManyRequestsError(
        f"You can make {limit} visuals a day. Please try again later.",
        code="VISUAL_LIMIT_REACHED",
        extra={"retry_after": retry_after},
    )


def title_from(prompt: str) -> str:
    """A short title for the draft row (the AI replaces it)."""
    text = " ".join(prompt.split())
    return (text[:1].upper() + text[1:])[:200]


async def request_visual(
    session: AsyncSession,
    user: CurrentUser,
    req: GenerateVisualIn,
    ai: AIClient,
    background_tasks: BackgroundTasks,
) -> JobCreatedOut:
    """Create the draft visual + its GENERATE_VISUAL job, and run it after the response."""
    topic_title = ""
    if req.topic_id is not None:
        [topic] = await syllabus_service.get_topics(session, [req.topic_id])  # 404 if unknown
        topic_title = topic.title
    await check_daily_limit(session, user)

    visual = Visual(
        id=uuid.uuid4(),
        topic_id=req.topic_id,
        kind=FIRST_GUESS_KIND[req.visual_type],
        title=title_from(req.prompt),
        prompt=req.prompt,
        style=req.style,
        status=ContentStatus.DRAFT,
        is_ai_generated=True,
        created_by=user.id,
    )
    session.add(visual)
    # Payload of ai_service/pipelines/visuals/decide_visual.py
    payload = {
        "visual_id": str(visual.id),
        "prompt": req.prompt,
        "visual_type": req.visual_type.value,
        "style": req.style.value,
        "topic_title": topic_title,
        "topic_id": str(req.topic_id) if req.topic_id else None,
    }
    job = await jobs.create_job(session, JobType.GENERATE_VISUAL, payload, requested_by=user.id)
    visual.job_id = job.id  # create_job committed the visual too; save the link
    await session.commit()

    # Runs after the response is sent (JOB_RUNNER=local, like core/jobs.enqueue_job). We need
    # our own task here so the visual is saved in the same commit as the job's success.
    # TODO(Mogith): move to Cloud Tasks together with core/jobs once JOB_RUNNER=cloudtasks exists.
    background_tasks.add_task(process_visual, visual.id, job.id, ai)
    logger.info("Visual %s queued as job %s", visual.id, job.id)
    return JobCreatedOut(job_id=job.id)


def apply_result(visual: Visual, output: dict[str, Any]) -> None:
    """Copy the pipeline output onto the row. The visual stays a draft for this student."""
    if output.get("visual_id") != str(visual.id):
        raise ValueError("The job result belongs to another visual")
    kind = VisualKind(output["kind"])  # raises for an unknown kind
    visual.kind = kind
    visual.title = (output.get("title") or visual.title)[:200]
    visual.mermaid_code = output.get("mermaid_code")
    visual.image_path = output.get("image_path")
    visual.width = output.get("width")
    visual.height = output.get("height")
    visual.labels = list(output.get("labels") or [])
    visual.alt_text = output.get("alt_text")
    visual.safety_passed = bool(output.get("safety_passed"))
    visual.prompt_version = output.get("prompt_version")
    visual.model = output.get("model")


async def run_visual_job(session: AsyncSession, visual: Visual, job: AIJob, ai: AIClient) -> None:
    """Run the job and save the visual. A failed visual is hidden from the student's list."""

    async def save(done: AIJob) -> None:
        apply_result(visual, (done.result or {}).get("result") or {})
        # The app only needs the id; everything else is now on the visuals row.
        done.result = {**(done.result or {}), "result": {"visual_id": str(visual.id)}}

    # run_job_inline never raises: AI errors, input errors and timeouts end as "failed".
    job = await jobs.run_job_inline(session, job, ai, on_success=save)
    if job.status == JobStatus.FAILED:
        if (job.error or "").startswith(f"{NOT_BIOLOGY_CODE}:"):
            visual.safety_passed = False  # refused by the safety check
            visual.status = ContentStatus.REJECTED
        else:
            visual.status = ContentStatus.ARCHIVED  # nothing usable was made
        await session.commit()


async def process_visual(visual_id: uuid.UUID, job_id: uuid.UUID, ai: AIClient) -> None:
    """Background task: make one visual. Uses its own DB session."""
    async with SessionLocal() as session:
        visual = await repository.get_visual(session, visual_id)
        job = await repository.get_job(session, job_id)
        if visual is None or job is None:
            logger.error("Visual %s or job %s not found", visual_id, job_id)
            return
        await run_visual_job(session, visual, job, ai)


# --------------------------------------------------------------------------- reports


async def report_visual(
    session: AsyncSession, user: CurrentUser, visual_id: uuid.UUID, req: ReportVisualIn
) -> VisualReportOut:
    """Save a report (status pending). 409 ALREADY_REPORTED while this student's last one is open."""
    visual = await _visible_visual(session, user, visual_id)
    already = ConflictError(
        "You already reported this visual. An admin will check it soon.",
        code="ALREADY_REPORTED",
    )
    if await repository.get_pending_report(session, visual.id, user.id) is not None:
        raise already
    details = (req.details or "").strip() or None
    report = VisualReport(
        visual_id=visual.id, user_id=user.id, reason=req.reason.value, details=details
    )
    session.add(report)
    try:
        await session.commit()
    except IntegrityError as exc:  # two taps at the same moment: uq_visual_reports_one_pending
        await session.rollback()
        raise already from exc
    await session.refresh(report)
    return VisualReportOut.model_validate(report, from_attributes=True)


async def list_reports(
    session: AsyncSession, base_url: str, status: ModerationStatus, limit: int = 50
) -> list[VisualReportAdminOut]:
    """Admin reports queue (admin/moderation_admin.py): each report with its visual."""
    rows = await repository.list_reports(session, status, limit)
    return [
        VisualReportAdminOut(
            id=report.id,
            visual_id=visual.id,
            reason=report.reason,
            details=report.details,
            status=report.status,
            created_at=report.created_at,
            reported_by=report.user_id,
            visual_title=visual.title,
            image_url=await storage.public_image_url(visual.image_path, base_url),
            mermaid_code=visual.mermaid_code,
        )
        for report, visual in rows
    ]
