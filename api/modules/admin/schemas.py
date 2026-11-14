"""Request / response models shared by the admin route files.

Area-specific admin schemas live in the owning module's schemas.py (e.g. syllabus, questions).
The dashboard is admin-only, so its models are here. They match BrAInBox_Mobile
apps/admin/lib/features/dashboard/domain/dashboard_models.dart.
"""

from typing import Literal

from pydantic import BaseModel


class ModuleStatus(BaseModel):
    """Response of the placeholder status routes."""

    module: str
    status: str


# ---------------------------------------------------------------- GET /admin/dashboard
# "aiReview" is camelCase on purpose: it is the app's enum value.
KpiKind = Literal["students", "quizzes", "aiReview", "reports"]


class DashboardKpi(BaseModel):
    kind: KpiKind
    label: str
    value: int
    delta: str  # e.g. "+8.4% vs last week"
    trend: Literal["good", "bad", "warning"]
    sparkline: list[int]  # the last 8 days, oldest first


class DashboardActivity(BaseModel):
    day_labels: list[str]  # 14 days: "24 Sep", "25", ..., "1 Oct", ...
    quizzes: list[int]
    notes_generated: list[int]


class DashboardReport(BaseModel):
    title: str
    subtitle: str
    meta: str
    severity: Literal["high", "medium"] | None = None


class DashboardMissedTopic(BaseModel):
    topic: str
    unit: str  # "Unit 6 · Genetics"
    miss_rate: float  # 0-1
    attempts: int
    top_misconception: str


class DashboardOut(BaseModel):
    title: str = "Dashboard"
    message: str | None = None
    batch_label: str  # "A/L 2027 batch"
    kpis: list[DashboardKpi]
    activity: DashboardActivity
    recent_reports: list[DashboardReport]
    missed_topics_attempts: int
    missed_topics: list[DashboardMissedTopic]
