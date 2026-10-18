"""All admin routes, mounted under /api/v1/admin.

The admin role check is added ONCE here, so every route in the files below is admin-only.
Each area has its own file and owner (see README.md).
"""

from fastapi import APIRouter, Depends

from api.core.security import require_role
from api.modules.admin import (
    analytics_admin,
    content_admin,
    knowledge_admin,
    moderation_admin,
    questions_admin,
    rag_admin,
    syllabus_admin,
    users_admin,
)
from shared.enums import UserRole

router = APIRouter(prefix="/admin", dependencies=[Depends(require_role(UserRole.ADMIN))])

router.include_router(content_admin.router)  # Samni
router.include_router(rag_admin.router)  # Samni
router.include_router(questions_admin.router)  # Udith
router.include_router(knowledge_admin.router)  # Keshomigha
router.include_router(syllabus_admin.router)  # Keshomigha
router.include_router(analytics_admin.router)  # Keshomigha
router.include_router(moderation_admin.router)  # Mogith
router.include_router(users_admin.router)  # Mogith
