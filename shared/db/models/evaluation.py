"""Evaluations of written (structured / essay) answers. Owner: Keshomigha."""

import uuid
from typing import Any

from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from shared.enums import JobStatus


class Evaluation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "evaluations"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), index=True
    )
    response_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("responses.id", ondelete="SET NULL"), index=True
    )
    answer_text: Mapped[str | None] = mapped_column(Text)  # typed answer
    answer_image_path: Mapped[str | None] = mapped_column(String(500))  # handwritten photo
    ocr_text: Mapped[str | None] = mapped_column(Text)  # text read from the photo
    estimated_marks: Mapped[float | None] = mapped_column(Float)
    max_marks: Mapped[float | None] = mapped_column(Float)
    # Which answer points were matched: [{"answer_point_id": "...", "matched": true}, ...]
    matched_points: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default="[]"
    )
    feedback: Mapped[str | None] = mapped_column(Text)
    status: Mapped[JobStatus] = mapped_column(str_enum(JobStatus), default=JobStatus.QUEUED)
    prompt_version: Mapped[str | None] = mapped_column(String(50))
