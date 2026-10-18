"""Admin routes: questions. Owner: Udith.

Mounted under /api/v1/admin/questions by `admin/router.py`, which already
requires the admin role for every route in this file.

Planned endpoints:
    GET/POST/PATCH /admin/questions (question bank)
    POST /admin/questions/{id}/options (MCQ -> misconception mapping)
    GET /admin/questions/review-queue, POST /admin/questions/{id}/review
    POST /admin/questions/generate (GENERATE_QUESTIONS job)
    POST /admin/questions/past-papers/import

Admin routes call the services of the owning modules (e.g. `api.modules.content.service`);
they do not have their own SQL.
"""

from fastapi import APIRouter

from api.core.security import CurrentUserDep
from api.modules.admin.schemas import ModuleStatus

router = APIRouter(prefix="/questions", tags=["Admin: questions"])


@router.get("/status", response_model=ModuleStatus, summary="Placeholder: admin area status")
async def area_status(admin: CurrentUserDep) -> ModuleStatus:
    # TODO(Udith): replace with the endpoints listed above.
    return ModuleStatus(module="questions_admin", status="todo")
