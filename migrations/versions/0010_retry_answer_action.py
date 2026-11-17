"""Recommendations: a new action "retry_answer" (compare with the model answer and re-attempt
a written question).

Enums are stored as text with a CHECK constraint, so adding a value means recreating the CHECK
on every column that uses the enum (recommendations.action_type, plan_items.action_type).

Revision ID: 0010
Revises: 0009
"""

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels = None
depends_on = None

OLD = ["revise_note", "watch_video", "practice_quiz", "view_visual", "reassess", "ask_community"]
NEW = [*OLD, "retry_answer"]
TABLES = ["recommendations", "plan_items"]


def _check(values: list[str]) -> str:
    return "action_type IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def _name(table: str) -> str:
    # op.f(): the name is already final, so the naming convention must not prefix it again.
    return op.f(f"ck_{table}_recommendation_action")  # type: ignore[no-any-return]


def upgrade() -> None:
    for table in TABLES:
        op.drop_constraint(_name(table), table, type_="check")
        op.create_check_constraint(_name(table), table, _check(NEW))


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"DELETE FROM {table} WHERE action_type = 'retry_answer'")  # noqa: S608
        op.drop_constraint(_name(table), table, type_="check")
        op.create_check_constraint(_name(table), table, _check(OLD))
