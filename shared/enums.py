"""Enums shared by both services and stored in the database as VARCHAR(32) + a CHECK constraint.

Rules (read before changing anything here):
  * Values are lower-case strings. The database stores the *value* (e.g. "admin").
  * Never rename or remove a value that may already be stored.
  * Adding a value needs a small migration that recreates the CHECK constraint of every
    column using the enum (see docs/database.md -> "Adding an enum value").
  * Some enums keep older values that existing code already writes (marked "kept:").
"""

from enum import StrEnum

# ============================================================================ users


class UserRole(StrEnum):
    STUDENT = "student"
    ADMIN = "admin"


class Stream(StrEnum):
    BIO_SCIENCE = "bio_science"


class TargetGrade(StrEnum):
    # Stored upper-case in student_profiles.target_grade ("A" / "B" / "C" / "S"),
    # because the profiles API already uses upper-case grades.
    A = "A"
    B = "B"
    C = "C"
    S = "S"


class PreferredTime(StrEnum):
    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"
    NIGHT = "night"


class ThemeMode(StrEnum):
    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"


class EmailCodePurpose(StrEnum):
    VERIFY_EMAIL = "verify_email"
    RESET_PASSWORD = "reset_password"


class DevicePlatform(StrEnum):
    ANDROID = "android"
    WEB = "web"


class NotificationType(StrEnum):
    STUDY_REMINDER = "study_reminder"
    PLAN_READY = "plan_ready"
    JOB_DONE = "job_done"
    COMMUNITY_REPLY = "community_reply"
    CONTENT_APPROVED = "content_approved"
    SYSTEM = "system"


# ============================================================================ content


class ContentStatus(StrEnum):
    """Life cycle of anything an admin must approve (notes, questions, visuals...)."""

    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    ARCHIVED = "archived"  # kept: already used


class ContentSource(StrEnum):
    AI = "ai"
    ADMIN = "admin"


class NoteKind(StrEnum):
    """Values of notes.note_type."""

    FULL = "full"
    SHORT = "short"


class UploadStatus(StrEnum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class LibraryItemType(StrEnum):
    NOTE = "note"
    SUMMARY = "summary"
    VISUAL = "visual"
    QUESTION = "question"
    RESOURCE = "resource"
    POST = "post"


class VisualKind(StrEnum):
    DIAGRAM = "diagram"  # Mermaid diagram (rendered on the device)
    ILLUSTRATION = "illustration"  # AI-generated image
    FLOWCHART = "flowchart"  # kept: already used
    TABLE = "table"  # kept: already used


class VisualStyle(StrEnum):
    """The style cards on "Generate a visual" (Figma B10)."""

    FLAT_COLOUR = "flat_colour"
    TEXTBOOK_LINE = "textbook_line"
    CROSS_SECTION = "cross_section"


class VisualType(StrEnum):
    """What the student wants to see. Only a hint for the AI (not stored)."""

    PROCESS = "process"  # -> flowchart
    STRUCTURE = "structure"  # -> diagram or illustration
    COMPARISON = "comparison"  # -> table / flowchart


class ReportStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class VisualReportReason(StrEnum):
    WRONG_LABEL = "wrong_label"
    INACCURATE = "inaccurate"
    UNCLEAR = "unclear"
    OFFENSIVE = "offensive"
    OTHER = "other"


# ============================================================================ questions and exams


class QuestionType(StrEnum):
    MCQ = "mcq"
    STRUCTURED = "structured"
    ESSAY = "essay"


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class QuestionOrigin(StrEnum):
    """Values of questions.source (where a question came from)."""

    PAST_PAPER = "past_paper"
    AI = "ai"
    ADMIN = "admin"
    MANUAL = "manual"  # kept: the old default, same meaning as "admin"


class PaperPart(StrEnum):
    PART_1 = "part_1"
    PART_2A = "part_2a"
    PART_2B = "part_2b"


class ReviewerType(StrEnum):
    AI = "ai"
    ADMIN = "admin"


class ReviewDecision(StrEnum):
    APPROVE = "approve"
    REVISE = "revise"
    REJECT = "reject"


class QuestionReportReason(StrEnum):
    WRONG_ANSWER = "wrong_answer"
    UNCLEAR = "unclear"
    TYPO = "typo"
    OUT_OF_SYLLABUS = "out_of_syllabus"
    DUPLICATE = "duplicate"
    OTHER = "other"


class PaperKind(StrEnum):
    """Values of papers.paper_type."""

    QUIZ = "quiz"
    MODEL_PAPER = "model_paper"
    PAST_PAPER = "past_paper"
    DIAGNOSTIC = "diagnostic"
    AI_GENERATED = "ai_generated"  # kept: a personal practice paper (exams module)


class PaperStatus(StrEnum):
    GENERATING = "generating"
    READY = "ready"
    FAILED = "failed"
    ARCHIVED = "archived"


class AttemptKind(StrEnum):
    DIAGNOSTIC = "diagnostic"
    QUIZ = "quiz"
    EXAM = "exam"
    PRACTICE = "practice"


class AttemptMode(StrEnum):
    PRACTICE = "practice"
    TIMED = "timed"


class AttemptStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    EVALUATED = "evaluated"
    ABANDONED = "abandoned"
    GRADED = "graded"  # kept: what the diagnostic and exams modules write when marked


class ModelAnswerSource(StrEnum):
    MARKING_SCHEME = "marking_scheme"
    ADMIN = "admin"
    AI = "ai"


class EvaluationMethod(StrEnum):
    KEYWORD = "keyword"
    SEMANTIC = "semantic"
    HYBRID = "hybrid"


# ============================================================================ performance


class MistakeType(StrEnum):
    MISCONCEPTION = "misconception"
    KNOWLEDGE_GAP = "knowledge_gap"
    INCOMPLETE = "incomplete"
    WRONG_TERM = "wrong_term"
    CARELESS = "careless"
    CONCEPTUAL = "conceptual"  # kept: older value
    FACTUAL = "factual"  # kept: older value
    TERMINOLOGY = "terminology"  # kept: older value


class MasterySource(StrEnum):
    DIAGNOSTIC = "diagnostic"
    PRACTICE = "practice"
    EXAM = "exam"
    QUIZ = "quiz"  # kept: allowed by unit_mastery.source


# ============================================================================ recommendations


class ResourceKind(StrEnum):
    VIDEO = "video"
    NOTE = "note"
    VISUAL = "visual"
    ARTICLE = "article"
    PAST_PAPER = "past_paper"


class ResourceProvider(StrEnum):
    YOUTUBE = "youtube"
    INTERNAL = "internal"
    WEB = "web"


class RecommendationAction(StrEnum):
    REVISE_NOTE = "revise_note"
    WATCH_VIDEO = "watch_video"
    PRACTICE_QUIZ = "practice_quiz"
    VIEW_VISUAL = "view_visual"
    REASSESS = "reassess"
    ASK_COMMUNITY = "ask_community"


class RecommendationStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    DISMISSED = "dismissed"
    EXPIRED = "expired"


class StudyPlanStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class PlanSource(StrEnum):
    DIAGNOSTIC = "diagnostic"
    RECOMMENDATIONS = "recommendations"
    MANUAL = "manual"


# ============================================================================ community


class GroupMemberRole(StrEnum):
    MEMBER = "member"
    MODERATOR = "moderator"


class ModerationStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    FLAGGED = "flagged"
    REMOVED = "removed"


class ContentReportReason(StrEnum):
    SPAM = "spam"
    OFFENSIVE = "offensive"
    WRONG_INFO = "wrong_info"
    OFF_TOPIC = "off_topic"
    OTHER = "other"


# ============================================================================ RAG


class SourceType(StrEnum):
    """Kinds of admin-approved documents that can be ingested into RAG (spec name:
    SourceDocumentType)."""

    NIE_RESOURCE_BOOK = "nie_resource_book"
    TEACHERS_GUIDE = "teachers_guide"
    SYLLABUS = "syllabus"
    PAST_PAPER = "past_paper"
    MARKING_SCHEME = "marking_scheme"
    OTHER = "other"
    TEACHER_GUIDE = "teacher_guide"  # kept: used by the RAG ingestion scripts
    APPROVED_NOTE = "approved_note"  # kept: used by the RAG ingestion scripts


class DocumentStatus(StrEnum):
    """Ingestion state of a RAG source document. The RAG pipeline writes the
    pending -> ingesting -> ready | failed values."""

    PENDING = "pending"
    INGESTING = "ingesting"
    READY = "ready"
    FAILED = "failed"
    UPLOADED = "uploaded"  # spec names, same meanings as above
    PROCESSING = "processing"
    INDEXED = "indexed"


# ============================================================================ AI jobs


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
    # Every value needs a pipeline in ai_service/jobs (a test checks this), so add
    # tag_post / embed_concepts / next_action together with their pipeline.
