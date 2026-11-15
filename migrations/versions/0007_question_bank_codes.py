"""Question bank: a short number per question (code "Q-1000") and an outdated flag.

Owner: Udith. Generated with `alembic revision --autogenerate` and then reviewed.
  * questions.number       IDENTITY starting at 1000. Postgres fills it for existing rows too,
                           so the NOT NULL column is safe to add.
  * questions.is_outdated  default false (admin "Mark outdated")

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-11 15:10:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "questions",
        sa.Column("number", sa.Integer(), sa.Identity(always=False, start=1000), nullable=False),
    )
    op.add_column(
        "questions",
        sa.Column("is_outdated", sa.Boolean(), server_default="false", nullable=False),
    )
    op.create_unique_constraint(op.f("uq_questions_number"), "questions", ["number"])


def downgrade() -> None:
    op.drop_constraint(op.f("uq_questions_number"), "questions", type_="unique")
    op.drop_column("questions", "is_outdated")
    op.drop_column("questions", "number")
