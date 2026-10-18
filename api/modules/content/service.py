"""Business logic for the content module. Owner: Samni.

Rules:
  * SQL lives in `repository.py`, not here.
  * To use another module, call ITS service (e.g. `from api.modules.syllabus import service`),
    never its repository.
  * AI work goes through `api.core.ai_client` / `api.core.jobs`, never directly to a provider.
"""

from api.modules.content.schemas import ModuleStatus

MODULE_NAME = "content"


async def get_status() -> ModuleStatus:
    """Placeholder used by the status route."""
    return ModuleStatus(module=MODULE_NAME, status="todo")


# TODO(Samni): list_topic_notes(topic_id) (approved only)
# TODO(Samni): create_upload(...) -> storage.upload_bytes + jobs.create_job(SUMMARIZE_UPLOAD)
# TODO(Samni): library CRUD
