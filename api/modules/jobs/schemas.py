"""Request / response models (Pydantic) for the jobs module. Owner: shared."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from shared.enums import JobStatus, JobType


class JobOut(BaseModel):
    """`GET /jobs/{job_id}`. The app polls it until `status` is succeeded or failed."""

    id: uuid.UUID
    job_type: JobType
    status: JobStatus
    progress: float  # 0.0 while queued / running, 1.0 when done
    # The pipeline's output when succeeded, e.g. {"visual_id": "..."} for GENERATE_VISUAL
    result: dict[str, Any] | None = None
    error: str | None = None  # one sentence a student can read, when failed
    error_code: str | None = None  # e.g. "NOT_BIOLOGY", for the app's ErrorMessages
    created_at: datetime
    finished_at: datetime | None = None
