"""Admin routes: content library. Owner: Samni.

Mounted under /api/v1/admin/content by `admin/router.py`, which already
requires the admin role for every route in this file.

    GET   /admin/content                 notes, short notes and diagrams (?type=&status=&unit=)
    POST  /admin/content/{id}/approve    {note?} -> the item
    POST  /admin/content/{id}/reject     {note?} -> the item
    PATCH /admin/content/{id}            {body_markdown} -> the item (notes only)

Diagrams are visuals waiting for review; approving one shares it with every student.
Admin routes call the services of the owning modules (here `api.modules.content.service`);
they do not have their own SQL.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Query, Request

from api.core.database import SessionDep
from api.core.security import CurrentUserDep
from api.modules.admin import service as admin_service
from api.modules.admin.schemas import ModuleStatus
from api.modules.content import service as content_service
from api.modules.content.schemas import (
    ContentEditIn,
    ContentItemOut,
    ContentItemType,
    ContentReviewIn,
)
from shared.enums import ContentStatus

router = APIRouter(prefix="/content", tags=["Admin: content"])

ReviewBody = Annotated[ContentReviewIn | None, Body()]


@router.get("/status", response_model=ModuleStatus, summary="Placeholder: admin area status")
async def area_status(admin: CurrentUserDep) -> ModuleStatus:
    return ModuleStatus(module="content_admin", status="todo")


@router.get("", response_model=list[ContentItemOut], summary="Content library")
async def list_content(
    request: Request,
    admin: CurrentUserDep,
    session: SessionDep,
    type: ContentItemType | None = None,  # noqa: A002 (the app's query name)
    status: ContentStatus | None = None,
    unit: Annotated[int | None, Query(ge=1)] = None,
) -> list[ContentItemOut]:
    """Last changed first (at most 200). Without `status`: notes in every status except
    archived, and only the diagrams waiting for review (draft / pending_review)."""
    return await content_service.admin_list_content(
        session, str(request.base_url), item_type=type, status=status, unit_number=unit
    )


async def _review(
    request: Request,
    admin: CurrentUserDep,
    session: SessionDep,
    item_id: uuid.UUID,
    approve: bool,
    body: ContentReviewIn | None,
) -> ContentItemOut:
    note = body.note if body else None
    item = await content_service.admin_review_content(
        session, admin.id, item_id, approve, note, str(request.base_url)
    )
    action = f"content.{'approve' if approve else 'reject'}"
    await admin_service.record_audit(
        session, admin, action, item.type, item_id, {"note": note} if note else None
    )
    return item


@router.post("/{item_id}/approve", response_model=ContentItemOut, summary="Approve an item")
async def approve(
    item_id: uuid.UUID,
    request: Request,
    admin: CurrentUserDep,
    session: SessionDep,
    body: ReviewBody = None,
) -> ContentItemOut:
    """Optional `{note}`. An older approved note of the same topic and kind is archived.
    Errors: 404 `CONTENT_NOT_FOUND`."""
    return await _review(request, admin, session, item_id, True, body)


@router.post("/{item_id}/reject", response_model=ContentItemOut, summary="Reject an item")
async def reject(
    item_id: uuid.UUID,
    request: Request,
    admin: CurrentUserDep,
    session: SessionDep,
    body: ReviewBody = None,
) -> ContentItemOut:
    """Optional `{note}` (why). Errors: 404 `CONTENT_NOT_FOUND`."""
    return await _review(request, admin, session, item_id, False, body)


@router.patch("/{item_id}", response_model=ContentItemOut, summary="Edit a note's text")
async def edit(
    item_id: uuid.UUID,
    req: ContentEditIn,
    request: Request,
    admin: CurrentUserDep,
    session: SessionDep,
) -> ContentItemOut:
    """Errors: 404 `CONTENT_NOT_FOUND` · 409 `CONTENT_NOT_EDITABLE` (a diagram) · 422."""
    item = await content_service.admin_edit_content(
        session, item_id, req.body_markdown, str(request.base_url)
    )
    await admin_service.record_audit(session, admin, "content.edit", item.type, item_id)
    return item
