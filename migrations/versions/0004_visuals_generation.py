"""Visuals generation: style, PNG size and AI flag on visuals; one pending report per student.

Owner: Mogith (visuals). Additive: new nullable / defaulted columns and one partial index.

visuals
  + style            VARCHAR(32) + CHECK ck_visuals_visual_style (flat_colour, textbook_line,
                     cross_section)
  + width, height    INTEGER, size of the stored PNG in pixels
  + is_ai_generated  BOOLEAN NOT NULL DEFAULT false (backfilled: true for rows made by a job)
visual_reports
  + uq_visual_reports_one_pending: one pending report per (visual, student)
    (older duplicate pending reports are set to "flagged" first, so nothing is deleted)

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: str | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- visuals: new columns
    op.add_column(
        'visuals',
        sa.Column(
            'style',
            sa.Enum('flat_colour', 'textbook_line', 'cross_section', name='visual_style',
                    native_enum=False, create_constraint=False, length=32),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        'ck_visuals_visual_style', 'visuals',
        "style IN ('flat_colour', 'textbook_line', 'cross_section')",
    )
    op.add_column('visuals', sa.Column('width', sa.Integer(), nullable=True))
    op.add_column('visuals', sa.Column('height', sa.Integer(), nullable=True))
    op.add_column(
        'visuals',
        sa.Column('is_ai_generated', sa.Boolean(), server_default='false', nullable=False),
    )
    # Rows made by an AI job (or from a student's prompt) are AI-generated.
    op.execute("UPDATE visuals SET is_ai_generated = true WHERE job_id IS NOT NULL OR prompt IS NOT NULL")

    # --- visual_reports: keep the newest pending report per (visual, student), flag the rest
    op.execute(
        """
        UPDATE visual_reports SET status = 'flagged'
        WHERE status = 'pending' AND id IN (
            SELECT id FROM (
                SELECT id, row_number() OVER (
                    PARTITION BY visual_id, user_id ORDER BY created_at DESC, id DESC
                ) AS n
                FROM visual_reports WHERE status = 'pending'
            ) ranked WHERE n > 1
        )
        """
    )
    op.create_index(
        'uq_visual_reports_one_pending', 'visual_reports', ['visual_id', 'user_id'],
        unique=True, postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index('uq_visual_reports_one_pending', table_name='visual_reports',
                  postgresql_where=sa.text("status = 'pending'"))
    op.drop_column('visuals', 'is_ai_generated')
    op.drop_column('visuals', 'height')
    op.drop_column('visuals', 'width')
    op.drop_constraint('ck_visuals_visual_style', 'visuals', type_='check')
    op.drop_column('visuals', 'style')
