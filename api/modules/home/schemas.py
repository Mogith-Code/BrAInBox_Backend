"""Request / response models (Pydantic) for the home module. Owner: Samni.

Matches the "B1 Home dashboard" design. The Flutter app depends on these shapes.
"""

import uuid

from pydantic import BaseModel

from api.modules.recommendations.schemas import PlanItemOut


class ActionTarget(BaseModel):
    unit_code: str | None = None
    topic_id: uuid.UUID | None = None


class NextBestAction(BaseModel):
    type: str  # "diagnostic" | "revise"
    title: str
    reason: str
    button_label: str
    minutes: int
    target: ActionTarget | None = None
    ai_generated: bool


class TodaysPlan(BaseModel):
    done: int
    total: int
    items: list[PlanItemOut]


class ContinueItem(BaseModel):
    topic_id: uuid.UUID
    title: str
    unit_code: str
    progress: int  # 0-100 (= unit mastery for now)


class HomeSummary(BaseModel):
    greeting_name: str
    initials: str
    streak_days: int
    days_to_exam: int | None
    next_best_action: NextBestAction
    todays_plan: TodaysPlan
    overall_mastery: int | None  # null until the student has any mastery data
    mastery_change_week: int
    continue_learning: list[ContinueItem]


class PlanItemUpdate(BaseModel):
    done: bool
