"""Business logic for the jobs module. Owner: shared.

Rules:
  * SQL lives in `repository.py`, not here.
  * To use another module, call ITS service (e.g. `from api.modules.syllabus import service`),
    never its repository.
  * AI work goes through `api.core.ai_client` / `api.core.jobs`, never directly to a provider.
"""

from api.modules.jobs.schemas import ModuleStatus

MODULE_NAME = "jobs"


async def get_status() -> ModuleStatus:
    """Placeholder used by the status route."""
    return ModuleStatus(module=MODULE_NAME, status="todo")


# TODO(shared): get_job(job_id, user) -> 404 if not found, 403 if not the requester / admin
