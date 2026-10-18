"""Enums shared by both services and stored in the database as plain strings.

Adding a new value is safe: the columns are VARCHAR(32) with no database check,
so no migration is needed. Never rename or remove a value that is already stored.
"""

from enum import StrEnum


class UserRole(StrEnum):
    STUDENT = "student"
    ADMIN = "admin"


class ContentStatus(StrEnum):
    """Life cycle of anything an admin must approve (notes, questions, visuals...)."""

    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobType(StrEnum):
    """Every long-running AI task. The ai_service dispatches on this value."""

    SUMMARIZE_UPLOAD = "summarize_upload"
    GENERATE_NOTES = "generate_notes"
    GENERATE_SHORT_NOTES = "generate_short_notes"
    GENERATE_VISUAL = "generate_visual"
    GENERATE_QUESTIONS = "generate_questions"
    REVIEW_QUESTIONS = "review_questions"
    MAP_MISCONCEPTIONS = "map_misconceptions"
    BUILD_PAPER = "build_paper"
    EVALUATE_ANSWER = "evaluate_answer"
    OCR_ANSWER = "ocr_answer"
    MODERATE_POST = "moderate_post"
    SUGGEST_ANSWER = "suggest_answer"
    RANK_RESOURCES = "rank_resources"
    RAG_INGEST = "rag_ingest"


class QuestionType(StrEnum):
    MCQ = "mcq"
    STRUCTURED = "structured"
    ESSAY = "essay"


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class MistakeType(StrEnum):
    CONCEPTUAL = "conceptual"
    MISCONCEPTION = "misconception"
    FACTUAL = "factual"
    TERMINOLOGY = "terminology"
    INCOMPLETE = "incomplete"
    CARELESS = "careless"


class VisualKind(StrEnum):
    DIAGRAM = "diagram"  # Mermaid diagram (rendered on the device)
    FLOWCHART = "flowchart"
    ILLUSTRATION = "illustration"  # AI-generated image
    TABLE = "table"


class ModerationStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    FLAGGED = "flagged"
    REMOVED = "removed"


class SourceType(StrEnum):
    """Kinds of admin-approved documents that can be ingested into RAG."""

    SYLLABUS = "syllabus"
    TEACHER_GUIDE = "teacher_guide"
    APPROVED_NOTE = "approved_note"
    MARKING_SCHEME = "marking_scheme"


class DocumentStatus(StrEnum):
    """Ingestion state of a RAG source document."""

    PENDING = "pending"
    INGESTING = "ingesting"
    READY = "ready"
    FAILED = "failed"
