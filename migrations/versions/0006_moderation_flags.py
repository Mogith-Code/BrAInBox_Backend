"""AI moderation flags on posts and replies (admin moderation queue).

Owner: Mogith. Generated with `alembic revision --autogenerate` and then reviewed.
Only adds nullable columns, so existing rows stay valid:
  * posts.moderation_score       how sure the AI moderator is (0-1)
  * replies.moderation_reason    the AI flag label, like posts.moderation_reason
  * replies.moderation_score

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-11 13:20:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("posts", sa.Column("moderation_score", sa.Numeric(4, 3), nullable=True))
    op.add_column("replies", sa.Column("moderation_reason", sa.Text(), nullable=True))
    op.add_column("replies", sa.Column("moderation_score", sa.Numeric(4, 3), nullable=True))


def downgrade() -> None:
    op.drop_column("replies", "moderation_score")
    op.drop_column("replies", "moderation_reason")
    op.drop_column("posts", "moderation_score")
