"""All database models.

Every model MUST be imported here, otherwise Alembic will not see its table
when you run `alembic revision --autogenerate`.
"""

from shared.db.base import Base
from shared.db.models.auth import EmailCode, PasswordResetToken
from shared.db.models.community import (
    CommunityGroup,
    ContentReport,
    GroupMember,
    Post,
    Reply,
    Vote,
)
from shared.db.models.content import LibraryItem, Note, Summary, Upload
from shared.db.models.evaluation import Evaluation
from shared.db.models.exam import Attempt, Paper, PaperQuestion, Response
from shared.db.models.knowledge import AnswerPoint, Keyword, ModelAnswer
from shared.db.models.performance import (
    ConceptMastery,
    MasterySnapshot,
    Mistake,
    StudyActivity,
    UnitMastery,
)
from shared.db.models.quality import QuestionReport, QuestionReview, QuestionStats
from shared.db.models.question import MCQOption, Misconception, Question, QuestionConcept
from shared.db.models.rag import DocumentChunk, SourceDocument
from shared.db.models.recommendation import (
    DailyPlanItem,
    PlanItem,
    Recommendation,
    Resource,
    StudyPlan,
)
from shared.db.models.syllabus import EMBEDDING_DIM, Concept, Topic, Unit
from shared.db.models.system import AIJob, AIUsageLog, AppConfig, AuditLog
from shared.db.models.user import DeviceToken, Notification, StudentProfile, User, UserSettings
from shared.db.models.visual import Visual, VisualReport

__all__ = [
    "EMBEDDING_DIM",
    "AIJob",
    "AIUsageLog",
    "AnswerPoint",
    "AppConfig",
    "Attempt",
    "AuditLog",
    "Base",
    "CommunityGroup",
    "Concept",
    "ConceptMastery",
    "ContentReport",
    "DailyPlanItem",
    "DeviceToken",
    "DocumentChunk",
    "EmailCode",
    "Evaluation",
    "GroupMember",
    "Keyword",
    "LibraryItem",
    "MCQOption",
    "MasterySnapshot",
    "Misconception",
    "Mistake",
    "ModelAnswer",
    "Note",
    "Notification",
    "Paper",
    "PaperQuestion",
    "PasswordResetToken",
    "PlanItem",
    "Post",
    "Question",
    "QuestionConcept",
    "QuestionReport",
    "QuestionReview",
    "QuestionStats",
    "Recommendation",
    "Reply",
    "Resource",
    "Response",
    "SourceDocument",
    "StudentProfile",
    "StudyActivity",
    "StudyPlan",
    "Summary",
    "Topic",
    "Unit",
    "UnitMastery",
    "Upload",
    "User",
    "UserSettings",
    "Visual",
    "VisualReport",
    "Vote",
]
