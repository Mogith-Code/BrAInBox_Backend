"""All database models.

Every model MUST be imported here, otherwise Alembic will not see its table
when you run `alembic revision --autogenerate`.
"""

from shared.db.base import Base
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
from shared.db.models.performance import ConceptMastery, Mistake
from shared.db.models.quality import QuestionReport, QuestionReview, QuestionStats
from shared.db.models.question import MCQOption, Misconception, Question, QuestionConcept
from shared.db.models.rag import DocumentChunk, SourceDocument
from shared.db.models.recommendation import PlanItem, Recommendation, Resource, StudyPlan
from shared.db.models.syllabus import EMBEDDING_DIM, Concept, Topic, Unit
from shared.db.models.system import AIJob, AIUsageLog, AuditLog
from shared.db.models.user import StudentProfile, User
from shared.db.models.visual import Visual, VisualReport

__all__ = [
    "EMBEDDING_DIM",
    "AIJob",
    "AIUsageLog",
    "AnswerPoint",
    "Attempt",
    "AuditLog",
    "Base",
    "CommunityGroup",
    "Concept",
    "ConceptMastery",
    "ContentReport",
    "DocumentChunk",
    "Evaluation",
    "GroupMember",
    "Keyword",
    "LibraryItem",
    "MCQOption",
    "Misconception",
    "Mistake",
    "ModelAnswer",
    "Note",
    "Paper",
    "PaperQuestion",
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
    "StudyPlan",
    "Summary",
    "Topic",
    "Unit",
    "Upload",
    "User",
    "Visual",
    "VisualReport",
    "Vote",
]
