"""Request / response models (Pydantic) for the quality module. Owner: Udith.

The admin models match BrAInBox_Mobile
apps/admin/lib/features/quality_review/domain/quality_review_models.dart.
"""

import uuid
from typing import Literal

from pydantic import BaseModel


class ModuleStatus(BaseModel):
    """Response of the placeholder status route."""

    module: str
    status: str


# ---------------------------------------------------------------- admin: quality review
CheckName = Literal[
    "Single correct answer", "Distractor quality", "Syllabus match", "Duplicate check"
]
CheckResult = Literal["pass", "review", "fail"]


class QualityCheckOut(BaseModel):
    name: CheckName
    result: CheckResult
    note: str


class StudentReportOut(BaseModel):
    text: str  # e.g. "Wrong answer key"
    count: int


class QualityItemOut(BaseModel):
    id: uuid.UUID
    code: str
    stem: str
    unit_number: int | None = None
    topic_code: str | None = None  # e.g. "6.1"
    checks: list[QualityCheckOut]
    student_reports: list[StudentReportOut]


class QualityQueueOut(BaseModel):
    in_queue: int
    auto_check_failed: int
    with_student_reports: int
    avg_review_minutes: int | None = None  # last 30 days; null = no reviews yet
    items: list[QualityItemOut]


class ReviewDecisionIn(BaseModel):
    approve: bool
