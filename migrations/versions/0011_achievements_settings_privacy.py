"""Profile page: achievements (definitions + per-student unlocks with a "seen" flag) and the
Settings > Notifications / Data & privacy switches on user_settings.

Owner: Mogith (profiles). Only adds tables and defaulted columns, so existing rows stay valid.
The six achievement definitions are seeded here; the rule behind each id lives in
api/modules/profiles/service.py.

Revision ID: 0011
Revises: 0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACHIEVEMENTS = [
    {
        "id": "streak_7",
        "title": "7-day streak",
        "description": "Study 7 days in a row.",
        "icon": "streak",
        "badge_label": "Streak",
        "xp": 50,
        "order_index": 1,
    },
    {
        "id": "first_mastery",
        "title": "First topic mastered",
        "description": "Master your first topic.",
        "icon": "first_mastery",
        "badge_label": "Mastered",
        "xp": 50,
        "order_index": 2,
    },
    {
        "id": "unit_fixer",
        "title": "Unit fixer",
        "description": "Take a unit from Weak to Strong.",
        "icon": "unit_fixer",
        "badge_label": "Strong",
        "xp": 150,
        "order_index": 3,
    },
    {
        "id": "mcq_100",
        "title": "100 MCQs",
        "description": "Answer 100 MCQs.",
        "icon": "mcq_100",
        "badge_label": "100",
        "xp": 100,
        "order_index": 4,
    },
    {
        "id": "past_paper_pro",
        "title": "Past paper pro",
        "description": "Submit your first past paper.",
        "icon": "past_paper_pro",
        "badge_label": "Past paper",
        "xp": 100,
        "order_index": 5,
    },
    {
        "id": "unit_master",
        "title": "Unit master",
        "description": "Master every topic in a unit.",
        "icon": "unit_master",
        "badge_label": "Master",
        "xp": 200,
        "order_index": 6,
    },
]

SETTINGS_COLUMNS = [
    ("study_reminders", "true"),
    ("community_replies", "true"),
    ("improve_ai", "true"),
    ("show_name_in_community", "true"),
    ("share_research", "false"),
]


def upgrade() -> None:
    achievements = op.create_table(
        "achievements",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=80), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=False),
        sa.Column("icon", sa.String(length=30), nullable=False),
        sa.Column("badge_label", sa.String(length=30), nullable=True),
        sa.Column("xp", sa.Integer(), server_default="0", nullable=False),
        sa.Column("order_index", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_achievements")),
    )
    op.create_table(
        "user_achievements",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("achievement_id", sa.String(length=40), nullable=False),
        sa.Column("unlocked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("detail", sa.String(length=300), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["achievement_id"],
            ["achievements.id"],
            name=op.f("fk_user_achievements_achievement_id_achievements"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_achievements_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_achievements")),
        sa.UniqueConstraint(
            "user_id", "achievement_id", name="uq_user_achievements_user_achievement"
        ),
    )
    op.create_index(
        op.f("ix_user_achievements_achievement_id"),
        "user_achievements",
        ["achievement_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_user_achievements_user_id"), "user_achievements", ["user_id"], unique=False
    )
    for name, default in SETTINGS_COLUMNS:
        op.add_column(
            "user_settings",
            sa.Column(name, sa.Boolean(), server_default=default, nullable=False),
        )

    op.bulk_insert(achievements, ACHIEVEMENTS)


def downgrade() -> None:
    for name, _ in reversed(SETTINGS_COLUMNS):
        op.drop_column("user_settings", name)
    op.drop_index(op.f("ix_user_achievements_user_id"), table_name="user_achievements")
    op.drop_index(op.f("ix_user_achievements_achievement_id"), table_name="user_achievements")
    op.drop_table("user_achievements")
    op.drop_table("achievements")
