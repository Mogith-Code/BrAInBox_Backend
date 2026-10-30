"""Full schema: every table of the app, plus CHECK constraints and search indexes.

Schema owner: Keshomigha. Drafted with `alembic revision --autogenerate`, then reviewed and
hand-edited (autogenerate misses CHECK constraints and data fixes).
Additive and safe on a database with dev data: new tables, new nullable/defaulted columns,
new indexes and constraints. No table or existing column is dropped.

New tables
  user_settings, device_tokens, notifications   (users)
  mastery_snapshots                             (performance)
  app_config                                    (system: AL_EXAM_DATES, DAILY_LIMITS...)

Changed behaviour (ON DELETE)
  * content -> syllabus is now RESTRICT: notes, visuals, questions, misconceptions,
    question_concepts. Mark syllabus rows `is_outdated` instead of deleting them.
  * posts.author_id: CASCADE -> SET NULL (posts stay when the author deletes their account)
  * recommendations.resource_id: CASCADE -> SET NULL

Every enum column now has a CHECK constraint `ck_<table>_<enum_name>` (VARCHAR + CHECK).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: str | None = '0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (table, constraint name, condition) for every CHECK on a table that existed before 0003.
# Copied from the models; new tables above get theirs in create_table.
CHECKS: list[tuple[str, str, str]] = [
    ('ai_jobs', 'ck_ai_jobs_job_status', "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')"),
    ('ai_jobs', 'ck_ai_jobs_job_type', "job_type IN ('summarize_upload', 'generate_notes', 'generate_short_notes', 'generate_visual', 'generate_questions', 'review_questions', 'map_misconceptions', 'build_paper', 'evaluate_answer', 'ocr_answer', 'moderate_post', 'suggest_answer', 'rank_resources', 'rag_ingest')"),
    ('answer_points', 'ck_answer_points_marks_positive', 'marks > 0'),
    ('attempts', 'ck_attempts_attempt_kind', "kind IN ('diagnostic', 'quiz', 'exam', 'practice')"),
    ('attempts', 'ck_attempts_attempt_mode', "mode IN ('practice', 'timed')"),
    ('attempts', 'ck_attempts_status', "status IN ('in_progress', 'submitted', 'evaluated', 'abandoned', 'graded')"),
    ('concept_mastery', 'ck_concept_mastery_mastery_score_range', 'mastery_score BETWEEN 0 AND 1'),
    ('content_reports', 'ck_content_reports_moderation_status', "status IN ('pending', 'approved', 'flagged', 'removed')"),
    ('content_reports', 'ck_content_reports_target_type', "target_type IN ('post', 'reply')"),
    ('email_codes', 'ck_email_codes_attempts_not_negative', 'attempts >= 0'),
    ('email_codes', 'ck_email_codes_purpose', "purpose IN ('verify_email', 'reset_password')"),
    ('evaluations', 'ck_evaluations_confidence_range', 'confidence BETWEEN 0 AND 1'),
    ('evaluations', 'ck_evaluations_evaluation_method', "method IN ('keyword', 'semantic', 'hybrid')"),
    ('evaluations', 'ck_evaluations_job_status', "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')"),
    ('evaluations', 'ck_evaluations_keyword_coverage_range', 'keyword_coverage BETWEEN 0 AND 1'),
    ('evaluations', 'ck_evaluations_marks_range', 'estimated_marks >= 0 AND estimated_marks <= max_marks'),
    ('evaluations', 'ck_evaluations_semantic_score_range', 'semantic_score BETWEEN 0 AND 1'),
    ('group_members', 'ck_group_members_role', "role IN ('member', 'moderator', 'owner')"),
    ('library_items', 'ck_library_items_item_type', "item_type IN ('note', 'summary', 'visual', 'question', 'resource', 'post')"),
    ('mcq_options', 'ck_mcq_options_label', "label IN ('A', 'B', 'C', 'D', 'E')"),
    ('mistakes', 'ck_mistakes_mistake_type', "mistake_type IN ('misconception', 'knowledge_gap', 'incomplete', 'wrong_term', 'careless', 'conceptual', 'factual', 'terminology')"),
    ('model_answers', 'ck_model_answers_content_status', "status IN ('draft', 'pending_review', 'approved', 'rejected', 'archived')"),
    ('notes', 'ck_notes_content_source', "source IN ('ai', 'admin')"),
    ('notes', 'ck_notes_content_status', "status IN ('draft', 'pending_review', 'approved', 'rejected', 'archived')"),
    ('notes', 'ck_notes_note_type', "note_type IN ('full', 'short')"),
    ('papers', 'ck_papers_content_status', "status IN ('draft', 'pending_review', 'approved', 'rejected', 'archived')"),
    ('papers', 'ck_papers_paper_type', "paper_type IN ('quiz', 'model_paper', 'past_paper', 'diagnostic', 'ai_generated')"),
    ('plan_items', 'ck_plan_items_recommendation_action', "action_type IN ('revise_note', 'watch_video', 'practice_quiz', 'view_visual', 'reassess', 'ask_community')"),
    ('posts', 'ck_posts_ai_tag_confidence_range', 'ai_tag_confidence BETWEEN 0 AND 1'),
    ('posts', 'ck_posts_moderation_status', "moderation_status IN ('pending', 'approved', 'flagged', 'removed')"),
    ('question_reports', 'ck_question_reports_moderation_status', "status IN ('pending', 'approved', 'flagged', 'removed')"),
    ('question_reviews', 'ck_question_reviews_reviewer_type', "reviewer_type IN ('ai', 'admin', 'human')"),
    ('question_reviews', 'ck_question_reviews_verdict', "verdict IN ('approve', 'accept', 'revise', 'reject')"),
    ('questions', 'ck_questions_content_status', "status IN ('draft', 'pending_review', 'approved', 'rejected', 'archived')"),
    ('questions', 'ck_questions_difficulty', "difficulty IN ('easy', 'medium', 'hard')"),
    ('questions', 'ck_questions_marks_positive', 'marks > 0'),
    ('questions', 'ck_questions_paper_part', "paper_part IN ('part_1', 'part_2a', 'part_2b')"),
    ('questions', 'ck_questions_past_paper_year', "source <> 'past_paper' OR year IS NOT NULL"),
    ('questions', 'ck_questions_question_type', "question_type IN ('mcq', 'structured', 'essay')"),
    ('questions', 'ck_questions_source', "source IN ('past_paper', 'ai', 'admin', 'manual')"),
    ('recommendations', 'ck_recommendations_priority_range', 'priority BETWEEN 1 AND 5'),
    ('recommendations', 'ck_recommendations_recommendation_action', "action_type IN ('revise_note', 'watch_video', 'practice_quiz', 'view_visual', 'reassess', 'ask_community')"),
    ('recommendations', 'ck_recommendations_recommendation_status', "status IN ('pending', 'in_progress', 'done', 'dismissed', 'expired')"),
    ('replies', 'ck_replies_moderation_status', "moderation_status IN ('pending', 'approved', 'flagged', 'removed')"),
    ('resources', 'ck_resources_content_status', "status IN ('draft', 'pending_review', 'approved', 'rejected', 'archived')"),
    ('resources', 'ck_resources_quality_score_range', 'quality_score BETWEEN 0 AND 1'),
    ('source_documents', 'ck_source_documents_document_status', "status IN ('pending', 'ingesting', 'ready', 'failed', 'uploaded', 'processing', 'indexed')"),
    ('source_documents', 'ck_source_documents_source_type', "source_type IN ('nie_resource_book', 'teachers_guide', 'syllabus', 'past_paper', 'marking_scheme', 'other', 'teacher_guide', 'approved_note')"),
    ('student_profiles', 'ck_student_profiles_confidence_range', 'confidence BETWEEN 0 AND 100'),
    ('student_profiles', 'ck_student_profiles_exam_year_range', 'exam_year BETWEEN 2025 AND 2035'),
    ('student_profiles', 'ck_student_profiles_hours_per_day_range', 'hours_per_day > 0 AND hours_per_day <= 12'),
    ('student_profiles', 'ck_student_profiles_preferred_time', "preferred_time IN ('morning', 'afternoon', 'evening', 'night')"),
    ('student_profiles', 'ck_student_profiles_stream', "stream IN ('bio_science')"),
    ('student_profiles', 'ck_student_profiles_target_grade', "target_grade IN ('A', 'B', 'C', 'S')"),
    ('study_plans', 'ck_study_plans_dates_in_order', 'end_date >= start_date'),
    ('study_plans', 'ck_study_plans_plan_source', "generated_from IN ('diagnostic', 'recommendations', 'manual')"),
    ('study_plans', 'ck_study_plans_study_plan_status', "status IN ('active', 'completed', 'archived')"),
    ('summaries', 'ck_summaries_upload_status', "status IN ('uploaded', 'processing', 'ready', 'failed')"),
    ('unit_mastery', 'ck_unit_mastery_mastery_range', 'mastery BETWEEN 0 AND 100'),
    ('unit_mastery', 'ck_unit_mastery_source', "source IN ('diagnostic', 'practice', 'exam', 'quiz')"),
    ('uploads', 'ck_uploads_job_status', "processing_status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')"),
    ('uploads', 'ck_uploads_size_bytes_range', 'size_bytes > 0 AND size_bytes <= 20971520'),
    ('users', 'ck_users_phone_e164', "phone ~ '^\\+[1-9][0-9]{7,14}$'"),
    ('users', 'ck_users_user_role', "role IN ('student', 'admin')"),
    ('visual_reports', 'ck_visual_reports_moderation_status', "status IN ('pending', 'approved', 'flagged', 'removed')"),
    ('visuals', 'ck_visuals_content_status', "status IN ('draft', 'pending_review', 'approved', 'rejected', 'archived')"),
    ('visuals', 'ck_visuals_visual_kind', "kind IN ('diagram', 'illustration', 'flowchart', 'table')"),
    ('votes', 'ck_votes_one_target', 'num_nonnulls(post_id, reply_id) = 1'),
    ('votes', 'ck_votes_value_plus_minus_one', 'value IN (-1, 1)'),
]


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('app_config',
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], name=op.f('fk_app_config_updated_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('key', name=op.f('pk_app_config'))
    )
    op.create_index(op.f('ix_app_config_updated_by'), 'app_config', ['updated_by'], unique=False)
    op.create_table('device_tokens',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('fcm_token', sa.Text(), nullable=False),
    sa.Column('platform', sa.Enum('android', 'web', name='device_platform', native_enum=False, create_constraint=False, length=32), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("platform IN ('android', 'web')", name=op.f('ck_device_tokens_device_platform')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_device_tokens_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_device_tokens')),
    sa.UniqueConstraint('fcm_token', name=op.f('uq_device_tokens_fcm_token'))
    )
    op.create_index(op.f('ix_device_tokens_user_id'), 'device_tokens', ['user_id'], unique=False)
    op.create_table('mastery_snapshots',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('snapshot_date', sa.Date(), nullable=False),
    sa.Column('overall_mastery', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('unit_breakdown', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('overall_mastery BETWEEN 0 AND 100', name=op.f('ck_mastery_snapshots_overall_mastery_range')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_mastery_snapshots_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_mastery_snapshots')),
    sa.UniqueConstraint('user_id', 'snapshot_date', name='uq_mastery_snapshots_user_date')
    )
    op.create_index(op.f('ix_mastery_snapshots_user_id'), 'mastery_snapshots', ['user_id'], unique=False)
    op.create_table('notifications',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('type', sa.Enum('study_reminder', 'plan_ready', 'job_done', 'community_reply', 'content_approved', 'system', name='notification_type', native_enum=False, create_constraint=False, length=32), nullable=False),
    sa.Column('title', sa.String(length=120), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("type IN ('study_reminder', 'plan_ready', 'job_done', 'community_reply', 'content_approved', 'system')", name=op.f('ck_notifications_notification_type')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_notifications_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_notifications'))
    )
    op.create_index('ix_notifications_unread', 'notifications', ['user_id'], unique=False, postgresql_where=sa.text('read_at IS NULL'))
    op.create_index('ix_notifications_user_created', 'notifications', ['user_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_notifications_user_id'), 'notifications', ['user_id'], unique=False)
    op.create_table('user_settings',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('theme', sa.Enum('system', 'light', 'dark', name='theme_mode', native_enum=False, create_constraint=False, length=32), server_default='system', nullable=False),
    sa.Column('notifications_enabled', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('daily_reminder_time', sa.Time(), nullable=True),
    sa.Column('email_updates', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("theme IN ('system', 'light', 'dark')", name=op.f('ck_user_settings_theme_mode')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_user_settings_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', name=op.f('pk_user_settings'))
    )
    op.create_index('ix_ai_jobs_requested_by_created', 'ai_jobs', ['requested_by', 'created_at'], unique=False)
    op.create_index('ix_ai_jobs_status_created', 'ai_jobs', ['status', 'created_at'], unique=False)
    op.add_column('ai_usage_log', sa.Column('user_id', sa.UUID(), nullable=True))
    op.add_column('ai_usage_log', sa.Column('images', sa.Integer(), server_default='0', nullable=False))
    op.create_index('ix_ai_usage_log_created', 'ai_usage_log', ['created_at'], unique=False)
    op.create_index('ix_ai_usage_log_operation_created', 'ai_usage_log', ['operation', 'created_at'], unique=False)
    op.create_index('ix_ai_usage_log_user_created', 'ai_usage_log', ['user_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_ai_usage_log_user_id'), 'ai_usage_log', ['user_id'], unique=False)
    op.create_foreign_key(op.f('fk_ai_usage_log_user_id_users'), 'ai_usage_log', 'users', ['user_id'], ['id'], ondelete='SET NULL')
    op.add_column('answer_points', sa.Column('is_required', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('answer_points', sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=768), nullable=True))
    op.add_column('answer_points', sa.Column('embedding_model', sa.String(length=64), nullable=True))
    op.create_index('ix_answer_points_embedding_hnsw', 'answer_points', ['embedding'], unique=False, postgresql_using='hnsw', postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.add_column('attempts', sa.Column('kind', sa.Enum('diagnostic', 'quiz', 'exam', 'practice', name='attempt_kind', native_enum=False, create_constraint=False, length=32), server_default='quiz', nullable=False))
    op.add_column('attempts', sa.Column('mode', sa.Enum('practice', 'timed', name='attempt_mode', native_enum=False, create_constraint=False, length=32), server_default='practice', nullable=False))
    op.add_column('attempts', sa.Column('unit_id', sa.UUID(), nullable=True))
    op.add_column('attempts', sa.Column('topic_id', sa.UUID(), nullable=True))
    op.add_column('attempts', sa.Column('question_ids', postgresql.ARRAY(sa.UUID()), server_default='{}', nullable=False))
    op.add_column('attempts', sa.Column('time_limit_minutes', sa.Integer(), nullable=True))
    op.add_column('attempts', sa.Column('max_score', sa.Float(), nullable=True))
    op.add_column('attempts', sa.Column('percentage', sa.Float(), nullable=True))
    op.create_index(op.f('ix_attempts_topic_id'), 'attempts', ['topic_id'], unique=False)
    op.create_index(op.f('ix_attempts_unit_id'), 'attempts', ['unit_id'], unique=False)
    op.create_index('ix_attempts_user_kind_status', 'attempts', ['user_id', 'kind', 'status'], unique=False)
    # Existing attempts: work out their kind from the paper, then keep only the newest
    # unfinished diagnostic per student (older ones become "abandoned").
    op.execute(
        "UPDATE attempts SET kind = 'diagnostic' FROM papers "
        "WHERE attempts.paper_id = papers.id AND papers.paper_type = 'diagnostic'"
    )
    op.execute(
        "UPDATE attempts SET kind = 'exam' FROM papers WHERE attempts.paper_id = papers.id "
        "AND papers.paper_type IN ('ai_generated', 'model_paper', 'past_paper')"
    )
    op.execute(
        "UPDATE attempts SET status = 'abandoned' WHERE id IN ("
        " SELECT id FROM (SELECT id, row_number() OVER ("
        "  PARTITION BY user_id ORDER BY created_at DESC) AS n FROM attempts"
        "  WHERE kind = 'diagnostic' AND status = 'in_progress') AS t WHERE n > 1)"
    )
    op.create_index('uq_attempts_one_open_diagnostic', 'attempts', ['user_id'], unique=True, postgresql_where=sa.text("kind = 'diagnostic' AND status = 'in_progress'"))
    op.create_foreign_key(op.f('fk_attempts_topic_id_topics'), 'attempts', 'topics', ['topic_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key(op.f('fk_attempts_unit_id_units'), 'attempts', 'units', ['unit_id'], ['id'], ondelete='SET NULL')
    op.add_column('audit_log', sa.Column('before', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('audit_log', sa.Column('after', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_index('ix_audit_log_actor_created', 'audit_log', ['actor_id', 'created_at'], unique=False)
    op.create_index('ix_audit_log_target', 'audit_log', ['target_type', 'target_id'], unique=False)
    op.add_column('community_groups', sa.Column('slug', sa.String(length=100), nullable=True))
    op.add_column('community_groups', sa.Column('is_default', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('community_groups', sa.Column('member_count', sa.Integer(), server_default='0', nullable=False))
    op.create_unique_constraint(op.f('uq_community_groups_slug'), 'community_groups', ['slug'])
    op.add_column('concept_mastery', sa.Column('correct_count', sa.Integer(), server_default='0', nullable=False))
    op.add_column('concepts', sa.Column('code', sa.String(length=20), nullable=True))
    op.add_column('concepts', sa.Column('learning_outcome', sa.Text(), nullable=True))
    op.add_column('concepts', sa.Column('order_index', sa.Integer(), server_default='0', nullable=False))
    op.add_column('concepts', sa.Column('is_outdated', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('concepts', sa.Column('embedding_model', sa.String(length=64), nullable=True))
    op.create_index('ix_concepts_embedding_hnsw', 'concepts', ['embedding'], unique=False, postgresql_using='hnsw', postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.create_unique_constraint(op.f('uq_concepts_code'), 'concepts', ['code'])
    op.add_column('content_reports', sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('document_chunks', sa.Column('token_count', sa.Integer(), nullable=True))
    op.add_column('document_chunks', sa.Column('embedding_model', sa.String(length=64), nullable=True))
    op.create_index('ix_email_codes_email_purpose_created', 'email_codes', ['email', 'purpose', 'created_at'], unique=False)
    op.add_column('evaluations', sa.Column('method', sa.Enum('keyword', 'semantic', 'hybrid', name='evaluation_method', native_enum=False, create_constraint=False, length=32), nullable=True))
    op.add_column('evaluations', sa.Column('keyword_coverage', sa.Numeric(precision=4, scale=3), nullable=True))
    op.add_column('evaluations', sa.Column('semantic_score', sa.Numeric(precision=4, scale=3), nullable=True))
    op.add_column('evaluations', sa.Column('confidence', sa.Numeric(precision=4, scale=3), nullable=True))
    op.add_column('evaluations', sa.Column('manual_marks', sa.Float(), nullable=True))
    op.add_column('evaluations', sa.Column('manual_marked_by', sa.UUID(), nullable=True))
    op.add_column('evaluations', sa.Column('manual_marked_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('evaluations', sa.Column('model', sa.String(length=64), nullable=True))
    op.add_column('evaluations', sa.Column('job_id', sa.UUID(), nullable=True))
    op.create_index(op.f('ix_evaluations_job_id'), 'evaluations', ['job_id'], unique=False)
    op.create_index(op.f('ix_evaluations_manual_marked_by'), 'evaluations', ['manual_marked_by'], unique=False)
    op.create_foreign_key(op.f('fk_evaluations_manual_marked_by_users'), 'evaluations', 'users', ['manual_marked_by'], ['id'], ondelete='SET NULL')
    op.create_foreign_key(op.f('fk_evaluations_job_id_ai_jobs'), 'evaluations', 'ai_jobs', ['job_id'], ['id'], ondelete='SET NULL')
    op.create_index('uq_keywords_point_keyword_lower', 'keywords', ['answer_point_id', sa.literal_column('lower(keyword)')], unique=True)
    op.add_column('library_items', sa.Column('folder', sa.String(length=80), nullable=True))
    op.add_column('mcq_options', sa.Column('explanation_md', sa.Text(), nullable=True))
    op.create_index('uq_mcq_options_one_correct', 'mcq_options', ['question_id'], unique=True, postgresql_where=sa.text('is_correct'))
    op.create_unique_constraint('uq_mcq_options_question_label', 'mcq_options', ['question_id', 'label'])
    op.add_column('misconceptions', sa.Column('correction_md', sa.Text(), nullable=True))
    op.add_column('misconceptions', sa.Column('created_by', sa.UUID(), nullable=True))
    op.create_index(op.f('ix_misconceptions_created_by'), 'misconceptions', ['created_by'], unique=False)
    op.drop_constraint(op.f('fk_misconceptions_concept_id_concepts'), 'misconceptions', type_='foreignkey')
    op.create_foreign_key(op.f('fk_misconceptions_concept_id_concepts'), 'misconceptions', 'concepts', ['concept_id'], ['id'], ondelete='RESTRICT')
    op.create_foreign_key(op.f('fk_misconceptions_created_by_users'), 'misconceptions', 'users', ['created_by'], ['id'], ondelete='SET NULL')
    op.add_column('mistakes', sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_mistakes_user_concept', 'mistakes', ['user_id', 'concept_id'], unique=False)
    op.create_index('ix_mistakes_user_open', 'mistakes', ['user_id'], unique=False, postgresql_where=sa.text('resolved_at IS NULL'))
    op.add_column('model_answers', sa.Column('approved_by', sa.UUID(), nullable=True))
    op.add_column('model_answers', sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f('ix_model_answers_approved_by'), 'model_answers', ['approved_by'], unique=False)
    op.create_foreign_key(op.f('fk_model_answers_approved_by_users'), 'model_answers', 'users', ['approved_by'], ['id'], ondelete='SET NULL')
    op.add_column('notes', sa.Column('concept_id', sa.UUID(), nullable=True))
    op.add_column('notes', sa.Column('source', sa.Enum('ai', 'admin', name='content_source', native_enum=False, create_constraint=False, length=32), server_default='ai', nullable=False))
    op.add_column('notes', sa.Column('version', sa.Integer(), server_default='1', nullable=False))
    op.add_column('notes', sa.Column('reviewed_by', sa.UUID(), nullable=True))
    op.add_column('notes', sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('notes', sa.Column('review_comment', sa.Text(), nullable=True))
    op.add_column('notes', sa.Column('model', sa.String(length=64), nullable=True))
    op.add_column('notes', sa.Column('job_id', sa.UUID(), nullable=True))
    op.create_index(op.f('ix_notes_concept_id'), 'notes', ['concept_id'], unique=False)
    op.create_index(op.f('ix_notes_job_id'), 'notes', ['job_id'], unique=False)
    op.create_index(op.f('ix_notes_reviewed_by'), 'notes', ['reviewed_by'], unique=False)
    op.create_index(op.f('ix_notes_status'), 'notes', ['status'], unique=False)
    # Existing notes: keep only the newest approved note per topic and kind.
    op.execute(
        "UPDATE notes SET status = 'archived' WHERE id IN ("
        " SELECT id FROM (SELECT id, row_number() OVER ("
        "  PARTITION BY topic_id, note_type ORDER BY created_at DESC) AS n FROM notes"
        "  WHERE status = 'approved') AS t WHERE n > 1)"
    )
    op.create_index('uq_notes_topic_kind_approved', 'notes', ['topic_id', 'note_type'], unique=True, postgresql_where=sa.text("status = 'approved' AND concept_id IS NULL"))
    op.drop_constraint(op.f('fk_notes_topic_id_topics'), 'notes', type_='foreignkey')
    op.create_foreign_key(op.f('fk_notes_concept_id_concepts'), 'notes', 'concepts', ['concept_id'], ['id'], ondelete='RESTRICT')
    op.create_foreign_key(op.f('fk_notes_reviewed_by_users'), 'notes', 'users', ['reviewed_by'], ['id'], ondelete='SET NULL')
    op.create_foreign_key(op.f('fk_notes_job_id_ai_jobs'), 'notes', 'ai_jobs', ['job_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key(op.f('fk_notes_topic_id_topics'), 'notes', 'topics', ['topic_id'], ['id'], ondelete='RESTRICT')
    op.create_unique_constraint('uq_paper_questions_paper_question', 'paper_questions', ['paper_id', 'question_id'])
    op.add_column('papers', sa.Column('unit_ids', postgresql.ARRAY(sa.UUID()), server_default='{}', nullable=False))
    op.add_column('papers', sa.Column('blueprint', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False))
    op.add_column('papers', sa.Column('model', sa.String(length=64), nullable=True))
    op.add_column('papers', sa.Column('prompt_version', sa.String(length=50), nullable=True))
    op.add_column('papers', sa.Column('job_id', sa.UUID(), nullable=True))
    op.create_index(op.f('ix_papers_job_id'), 'papers', ['job_id'], unique=False)
    op.create_foreign_key(op.f('fk_papers_job_id_ai_jobs'), 'papers', 'ai_jobs', ['job_id'], ['id'], ondelete='SET NULL')
    op.add_column('plan_items', sa.Column('action_type', sa.Enum('revise_note', 'watch_video', 'practice_quiz', 'view_visual', 'reassess', 'ask_community', name='recommendation_action', native_enum=False, create_constraint=False, length=32), nullable=True))
    op.add_column('plan_items', sa.Column('concept_id', sa.UUID(), nullable=True))
    op.add_column('plan_items', sa.Column('recommendation_id', sa.UUID(), nullable=True))
    op.add_column('plan_items', sa.Column('done_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('plan_items', sa.Column('estimated_minutes', sa.SmallInteger(), nullable=True))
    op.create_index(op.f('ix_plan_items_concept_id'), 'plan_items', ['concept_id'], unique=False)
    op.create_index(op.f('ix_plan_items_recommendation_id'), 'plan_items', ['recommendation_id'], unique=False)
    op.create_foreign_key(op.f('fk_plan_items_recommendation_id_recommendations'), 'plan_items', 'recommendations', ['recommendation_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key(op.f('fk_plan_items_concept_id_concepts'), 'plan_items', 'concepts', ['concept_id'], ['id'], ondelete='SET NULL')
    op.add_column('posts', sa.Column('unit_id', sa.UUID(), nullable=True))
    op.add_column('posts', sa.Column('image_paths', postgresql.ARRAY(sa.Text()), server_default='{}', nullable=False))
    op.add_column('posts', sa.Column('ai_tag_topic_id', sa.UUID(), nullable=True))
    op.add_column('posts', sa.Column('ai_tag_confidence', sa.Numeric(precision=4, scale=3), nullable=True))
    op.add_column('posts', sa.Column('is_question', sa.Boolean(), server_default='true', nullable=False))
    op.add_column('posts', sa.Column('moderation_reason', sa.Text(), nullable=True))
    op.add_column('posts', sa.Column('score', sa.Integer(), server_default='0', nullable=False))
    op.add_column('posts', sa.Column('reply_count', sa.Integer(), server_default='0', nullable=False))
    op.add_column('posts', sa.Column('accepted_reply_id', sa.UUID(), nullable=True))
    op.add_column('posts', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    op.alter_column('posts', 'author_id',
               existing_type=sa.UUID(),
               nullable=True)
    op.create_index(op.f('ix_posts_accepted_reply_id'), 'posts', ['accepted_reply_id'], unique=False)
    op.create_index(op.f('ix_posts_ai_tag_topic_id'), 'posts', ['ai_tag_topic_id'], unique=False)
    op.create_index('ix_posts_group_created', 'posts', ['group_id', 'created_at'], unique=False)
    op.create_index('ix_posts_moderation_status', 'posts', ['moderation_status'], unique=False)
    op.create_index(op.f('ix_posts_unit_id'), 'posts', ['unit_id'], unique=False)
    op.drop_constraint(op.f('fk_posts_author_id_users'), 'posts', type_='foreignkey')
    op.create_foreign_key('fk_posts_accepted_reply_id_replies', 'posts', 'replies', ['accepted_reply_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key(op.f('fk_posts_unit_id_units'), 'posts', 'units', ['unit_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key(op.f('fk_posts_author_id_users'), 'posts', 'users', ['author_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key(op.f('fk_posts_ai_tag_topic_id_topics'), 'posts', 'topics', ['ai_tag_topic_id'], ['id'], ondelete='SET NULL')
    op.add_column('question_concepts', sa.Column('weight', sa.Numeric(precision=3, scale=2), server_default='1.0', nullable=False))
    op.drop_constraint(op.f('fk_question_concepts_concept_id_concepts'), 'question_concepts', type_='foreignkey')
    op.create_foreign_key(op.f('fk_question_concepts_concept_id_concepts'), 'question_concepts', 'concepts', ['concept_id'], ['id'], ondelete='RESTRICT')
    op.add_column('question_reports', sa.Column('resolved_by', sa.UUID(), nullable=True))
    op.add_column('question_reports', sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_question_reports_open', 'question_reports', ['status'], unique=False, postgresql_where=sa.text("status = 'pending'"))
    op.create_index(op.f('ix_question_reports_resolved_by'), 'question_reports', ['resolved_by'], unique=False)
    op.create_foreign_key(op.f('fk_question_reports_resolved_by_users'), 'question_reports', 'users', ['resolved_by'], ['id'], ondelete='SET NULL')
    op.add_column('question_reviews', sa.Column('checks', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False))
    op.add_column('question_reviews', sa.Column('model', sa.String(length=64), nullable=True))
    op.create_index('ix_question_reviews_question_created', 'question_reviews', ['question_id', 'created_at'], unique=False)
    op.add_column('question_stats', sa.Column('correct_rate', sa.Numeric(precision=4, scale=3), sa.Computed('CASE WHEN attempts_count = 0 THEN NULL ELSE round(correct_count::numeric / attempts_count, 3) END', persisted=True), nullable=True))
    op.add_column('question_stats', sa.Column('option_counts', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False))
    op.add_column('questions', sa.Column('unit_id', sa.UUID(), nullable=True))
    op.add_column('questions', sa.Column('stem_image_path', sa.Text(), nullable=True))
    op.add_column('questions', sa.Column('paper_part', sa.Enum('part_1', 'part_2a', 'part_2b', name='paper_part', native_enum=False, create_constraint=False, length=32), nullable=True))
    op.add_column('questions', sa.Column('question_number', sa.String(length=10), nullable=True))
    op.add_column('questions', sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=768), nullable=True))
    op.add_column('questions', sa.Column('embedding_model', sa.String(length=64), nullable=True))
    op.add_column('questions', sa.Column('model', sa.String(length=64), nullable=True))
    op.add_column('questions', sa.Column('job_id', sa.UUID(), nullable=True))
    op.create_index('ix_questions_embedding_hnsw', 'questions', ['embedding'], unique=False, postgresql_using='hnsw', postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.create_index(op.f('ix_questions_job_id'), 'questions', ['job_id'], unique=False)
    op.create_index(op.f('ix_questions_unit_id'), 'questions', ['unit_id'], unique=False)
    op.create_index('ix_questions_unit_type_status', 'questions', ['unit_id', 'question_type', 'status'], unique=False)
    op.create_index('uq_questions_past_paper_number', 'questions', ['year', 'paper_part', 'question_number'], unique=True, postgresql_where=sa.text("source = 'past_paper'"))
    op.drop_constraint(op.f('fk_questions_topic_id_topics'), 'questions', type_='foreignkey')
    op.create_foreign_key(op.f('fk_questions_topic_id_topics'), 'questions', 'topics', ['topic_id'], ['id'], ondelete='RESTRICT')
    op.create_foreign_key(op.f('fk_questions_unit_id_units'), 'questions', 'units', ['unit_id'], ['id'], ondelete='RESTRICT')
    op.create_foreign_key(op.f('fk_questions_job_id_ai_jobs'), 'questions', 'ai_jobs', ['job_id'], ['id'], ondelete='SET NULL')
    op.add_column('recommendations', sa.Column('action_type', sa.Enum('revise_note', 'watch_video', 'practice_quiz', 'view_visual', 'reassess', 'ask_community', name='recommendation_action', native_enum=False, create_constraint=False, length=32), nullable=True))
    op.add_column('recommendations', sa.Column('topic_id', sa.UUID(), nullable=True))
    op.add_column('recommendations', sa.Column('target_ref', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False))
    op.add_column('recommendations', sa.Column('priority', sa.SmallInteger(), server_default='3', nullable=False))
    op.add_column('recommendations', sa.Column('status', sa.Enum('pending', 'in_progress', 'done', 'dismissed', 'expired', name='recommendation_status', native_enum=False, create_constraint=False, length=32), server_default='pending', nullable=False))
    op.add_column('recommendations', sa.Column('ai_generated', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('recommendations', sa.Column('model', sa.String(length=64), nullable=True))
    op.add_column('recommendations', sa.Column('prompt_version', sa.String(length=50), nullable=True))
    op.add_column('recommendations', sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('recommendations', sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f('ix_recommendations_topic_id'), 'recommendations', ['topic_id'], unique=False)
    op.create_index('ix_recommendations_user_status_priority', 'recommendations', ['user_id', 'status', 'priority'], unique=False)
    op.drop_constraint(op.f('fk_recommendations_resource_id_resources'), 'recommendations', type_='foreignkey')
    op.create_foreign_key(op.f('fk_recommendations_resource_id_resources'), 'recommendations', 'resources', ['resource_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key(op.f('fk_recommendations_topic_id_topics'), 'recommendations', 'topics', ['topic_id'], ['id'], ondelete='SET NULL')
    op.add_column('replies', sa.Column('sources', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False))
    op.add_column('replies', sa.Column('score', sa.Integer(), server_default='0', nullable=False))
    op.add_column('replies', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('replies', sa.Column('job_id', sa.UUID(), nullable=True))
    op.create_index(op.f('ix_replies_job_id'), 'replies', ['job_id'], unique=False)
    op.create_index('ix_replies_post_created', 'replies', ['post_id', 'created_at'], unique=False)
    op.create_foreign_key(op.f('fk_replies_job_id_ai_jobs'), 'replies', 'ai_jobs', ['job_id'], ['id'], ondelete='SET NULL')
    op.add_column('resources', sa.Column('channel', sa.String(length=200), nullable=True))
    op.add_column('resources', sa.Column('thumbnail_url', sa.Text(), nullable=True))
    op.add_column('resources', sa.Column('language', sa.String(length=8), server_default='en', nullable=False))
    op.add_column('resources', sa.Column('quality_score', sa.Numeric(precision=4, scale=3), nullable=True))
    op.add_column('resources', sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('uq_resources_provider_external_id', 'resources', ['provider', 'external_id'], unique=True, postgresql_where=sa.text('external_id IS NOT NULL'))
    op.add_column('responses', sa.Column('image_paths', postgresql.ARRAY(sa.Text()), server_default='{}', nullable=False))
    op.add_column('responses', sa.Column('ocr_text', sa.Text(), nullable=True))
    op.add_column('responses', sa.Column('flagged', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('responses', sa.Column('answered_at', sa.DateTime(timezone=True), nullable=True))
    op.create_unique_constraint('uq_responses_attempt_question', 'responses', ['attempt_id', 'question_id'])
    op.add_column('source_documents', sa.Column('page_count', sa.Integer(), nullable=True))
    op.add_column('source_documents', sa.Column('indexed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('student_profiles', sa.Column('diagnostic_completed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('study_activity', sa.Column('minutes', sa.Integer(), server_default='0', nullable=False))
    op.add_column('study_activity', sa.Column('actions_count', sa.Integer(), server_default='0', nullable=False))
    op.add_column('study_plans', sa.Column('status', sa.Enum('active', 'completed', 'archived', name='study_plan_status', native_enum=False, create_constraint=False, length=32), server_default='active', nullable=False))
    op.add_column('study_plans', sa.Column('generated_from', sa.Enum('diagnostic', 'recommendations', 'manual', name='plan_source', native_enum=False, create_constraint=False, length=32), server_default='manual', nullable=False))
    # Existing plans: copy is_active into status, keeping only the newest active plan.
    op.execute("UPDATE study_plans SET status = CASE WHEN is_active THEN 'active' ELSE 'archived' END")
    op.execute(
        "UPDATE study_plans SET status = 'archived', is_active = false WHERE id IN ("
        " SELECT id FROM (SELECT id, row_number() OVER ("
        "  PARTITION BY user_id ORDER BY created_at DESC) AS n FROM study_plans"
        "  WHERE status = 'active') AS t WHERE n > 1)"
    )
    op.create_index('uq_study_plans_one_active', 'study_plans', ['user_id'], unique=True, postgresql_where=sa.text("status = 'active'"))
    op.add_column('summaries', sa.Column('key_points', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False))
    op.add_column('summaries', sa.Column('key_terms', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False))
    op.add_column('summaries', sa.Column('status', sa.Enum('uploaded', 'processing', 'ready', 'failed', name='upload_status', native_enum=False, create_constraint=False, length=32), server_default='ready', nullable=False))
    op.add_column('summaries', sa.Column('error', sa.Text(), nullable=True))
    op.add_column('summaries', sa.Column('model', sa.String(length=64), nullable=True))
    op.add_column('summaries', sa.Column('job_id', sa.UUID(), nullable=True))
    op.create_index(op.f('ix_summaries_job_id'), 'summaries', ['job_id'], unique=False)
    op.create_foreign_key(op.f('fk_summaries_job_id_ai_jobs'), 'summaries', 'ai_jobs', ['job_id'], ['id'], ondelete='SET NULL')
    op.add_column('units', sa.Column('is_outdated', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('uploads', sa.Column('title', sa.String(length=255), nullable=True))
    op.add_column('uploads', sa.Column('sha256', sa.String(length=64), nullable=True))
    op.add_column('uploads', sa.Column('page_count', sa.Integer(), nullable=True))
    op.add_column('uploads', sa.Column('extracted_text', sa.Text(), nullable=True))
    op.add_column('uploads', sa.Column('error', sa.Text(), nullable=True))
    op.create_index('ix_uploads_user_created', 'uploads', ['user_id', 'created_at'], unique=False)
    op.alter_column('users', 'role', server_default='student')
    op.add_column('users', sa.Column('avatar_url', sa.Text(), nullable=True))
    op.add_column('users', sa.Column('disabled_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f('ix_users_role'), 'users', ['role'], unique=False)
    op.create_index('uq_users_email_lower', 'users', [sa.literal_column('lower(email)')], unique=True, postgresql_where=sa.text('email IS NOT NULL'))
    op.add_column('visual_reports', sa.Column('resolved_by', sa.UUID(), nullable=True))
    op.add_column('visual_reports', sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f('ix_visual_reports_resolved_by'), 'visual_reports', ['resolved_by'], unique=False)
    op.create_foreign_key(op.f('fk_visual_reports_resolved_by_users'), 'visual_reports', 'users', ['resolved_by'], ['id'], ondelete='SET NULL')
    op.add_column('visuals', sa.Column('alt_text', sa.Text(), nullable=True))
    op.add_column('visuals', sa.Column('labels', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False))
    op.add_column('visuals', sa.Column('safety_passed', sa.Boolean(), nullable=True))
    op.add_column('visuals', sa.Column('verified_by', sa.UUID(), nullable=True))
    op.add_column('visuals', sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('visuals', sa.Column('model', sa.String(length=64), nullable=True))
    op.add_column('visuals', sa.Column('job_id', sa.UUID(), nullable=True))
    op.create_index('ix_visuals_concept_status', 'visuals', ['concept_id', 'status'], unique=False)
    op.create_index(op.f('ix_visuals_job_id'), 'visuals', ['job_id'], unique=False)
    op.create_index(op.f('ix_visuals_verified_by'), 'visuals', ['verified_by'], unique=False)
    op.drop_constraint(op.f('fk_visuals_concept_id_concepts'), 'visuals', type_='foreignkey')
    op.drop_constraint(op.f('fk_visuals_topic_id_topics'), 'visuals', type_='foreignkey')
    op.create_foreign_key(op.f('fk_visuals_verified_by_users'), 'visuals', 'users', ['verified_by'], ['id'], ondelete='SET NULL')
    op.create_foreign_key(op.f('fk_visuals_job_id_ai_jobs'), 'visuals', 'ai_jobs', ['job_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key(op.f('fk_visuals_concept_id_concepts'), 'visuals', 'concepts', ['concept_id'], ['id'], ondelete='RESTRICT')
    op.create_foreign_key(op.f('fk_visuals_topic_id_topics'), 'visuals', 'topics', ['topic_id'], ['id'], ondelete='RESTRICT')

    # CHECK constraints (including the enum ones) on tables that existed before 0003
    for table, name, condition in CHECKS:
        op.create_check_constraint(op.f(name), table, condition)
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    for table, name, _condition in reversed(CHECKS):
        op.execute(f'ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}')
    op.drop_constraint(op.f('fk_visuals_topic_id_topics'), 'visuals', type_='foreignkey')
    op.drop_constraint(op.f('fk_visuals_concept_id_concepts'), 'visuals', type_='foreignkey')
    op.drop_constraint(op.f('fk_visuals_job_id_ai_jobs'), 'visuals', type_='foreignkey')
    op.drop_constraint(op.f('fk_visuals_verified_by_users'), 'visuals', type_='foreignkey')
    op.create_foreign_key(op.f('fk_visuals_topic_id_topics'), 'visuals', 'topics', ['topic_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key(op.f('fk_visuals_concept_id_concepts'), 'visuals', 'concepts', ['concept_id'], ['id'], ondelete='SET NULL')
    op.drop_index(op.f('ix_visuals_verified_by'), table_name='visuals')
    op.drop_index(op.f('ix_visuals_job_id'), table_name='visuals')
    op.drop_index('ix_visuals_concept_status', table_name='visuals')
    op.drop_column('visuals', 'job_id')
    op.drop_column('visuals', 'model')
    op.drop_column('visuals', 'verified_at')
    op.drop_column('visuals', 'verified_by')
    op.drop_column('visuals', 'safety_passed')
    op.drop_column('visuals', 'labels')
    op.drop_column('visuals', 'alt_text')
    op.drop_constraint(op.f('fk_visual_reports_resolved_by_users'), 'visual_reports', type_='foreignkey')
    op.drop_index(op.f('ix_visual_reports_resolved_by'), table_name='visual_reports')
    op.drop_column('visual_reports', 'resolved_at')
    op.drop_column('visual_reports', 'resolved_by')
    op.drop_index('uq_users_email_lower', table_name='users', postgresql_where=sa.text('email IS NOT NULL'))
    op.drop_index(op.f('ix_users_role'), table_name='users')
    op.drop_column('users', 'disabled_at')
    op.alter_column('users', 'role', server_default=None)
    op.drop_column('users', 'avatar_url')
    op.drop_index('ix_uploads_user_created', table_name='uploads')
    op.drop_column('uploads', 'error')
    op.drop_column('uploads', 'extracted_text')
    op.drop_column('uploads', 'page_count')
    op.drop_column('uploads', 'sha256')
    op.drop_column('uploads', 'title')
    op.drop_column('units', 'is_outdated')
    op.drop_constraint(op.f('fk_summaries_job_id_ai_jobs'), 'summaries', type_='foreignkey')
    op.drop_index(op.f('ix_summaries_job_id'), table_name='summaries')
    op.drop_column('summaries', 'job_id')
    op.drop_column('summaries', 'model')
    op.drop_column('summaries', 'error')
    op.drop_column('summaries', 'status')
    op.drop_column('summaries', 'key_terms')
    op.drop_column('summaries', 'key_points')
    op.drop_index('uq_study_plans_one_active', table_name='study_plans', postgresql_where=sa.text("status = 'active'"))
    op.drop_column('study_plans', 'generated_from')
    op.drop_column('study_plans', 'status')
    op.drop_column('study_activity', 'actions_count')
    op.drop_column('study_activity', 'minutes')
    op.drop_column('student_profiles', 'diagnostic_completed_at')
    op.drop_column('source_documents', 'indexed_at')
    op.drop_column('source_documents', 'page_count')
    op.drop_constraint('uq_responses_attempt_question', 'responses', type_='unique')
    op.drop_column('responses', 'answered_at')
    op.drop_column('responses', 'flagged')
    op.drop_column('responses', 'ocr_text')
    op.drop_column('responses', 'image_paths')
    op.drop_index('uq_resources_provider_external_id', table_name='resources', postgresql_where=sa.text('external_id IS NOT NULL'))
    op.drop_column('resources', 'fetched_at')
    op.drop_column('resources', 'quality_score')
    op.drop_column('resources', 'language')
    op.drop_column('resources', 'thumbnail_url')
    op.drop_column('resources', 'channel')
    op.drop_constraint(op.f('fk_replies_job_id_ai_jobs'), 'replies', type_='foreignkey')
    op.drop_index('ix_replies_post_created', table_name='replies')
    op.drop_index(op.f('ix_replies_job_id'), table_name='replies')
    op.drop_column('replies', 'job_id')
    op.drop_column('replies', 'deleted_at')
    op.drop_column('replies', 'score')
    op.drop_column('replies', 'sources')
    op.drop_constraint(op.f('fk_recommendations_topic_id_topics'), 'recommendations', type_='foreignkey')
    op.drop_constraint(op.f('fk_recommendations_resource_id_resources'), 'recommendations', type_='foreignkey')
    op.create_foreign_key(op.f('fk_recommendations_resource_id_resources'), 'recommendations', 'resources', ['resource_id'], ['id'], ondelete='CASCADE')
    op.drop_index('ix_recommendations_user_status_priority', table_name='recommendations')
    op.drop_index(op.f('ix_recommendations_topic_id'), table_name='recommendations')
    op.drop_column('recommendations', 'completed_at')
    op.drop_column('recommendations', 'expires_at')
    op.drop_column('recommendations', 'prompt_version')
    op.drop_column('recommendations', 'model')
    op.drop_column('recommendations', 'ai_generated')
    op.drop_column('recommendations', 'status')
    op.drop_column('recommendations', 'priority')
    op.drop_column('recommendations', 'target_ref')
    op.drop_column('recommendations', 'topic_id')
    op.drop_column('recommendations', 'action_type')
    op.drop_constraint(op.f('fk_questions_job_id_ai_jobs'), 'questions', type_='foreignkey')
    op.drop_constraint(op.f('fk_questions_unit_id_units'), 'questions', type_='foreignkey')
    op.drop_constraint(op.f('fk_questions_topic_id_topics'), 'questions', type_='foreignkey')
    op.create_foreign_key(op.f('fk_questions_topic_id_topics'), 'questions', 'topics', ['topic_id'], ['id'], ondelete='SET NULL')
    op.drop_index('uq_questions_past_paper_number', table_name='questions', postgresql_where=sa.text("source = 'past_paper'"))
    op.drop_index('ix_questions_unit_type_status', table_name='questions')
    op.drop_index(op.f('ix_questions_unit_id'), table_name='questions')
    op.drop_index(op.f('ix_questions_job_id'), table_name='questions')
    op.drop_index('ix_questions_embedding_hnsw', table_name='questions', postgresql_using='hnsw', postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.drop_column('questions', 'job_id')
    op.drop_column('questions', 'model')
    op.drop_column('questions', 'embedding_model')
    op.drop_column('questions', 'embedding')
    op.drop_column('questions', 'question_number')
    op.drop_column('questions', 'paper_part')
    op.drop_column('questions', 'stem_image_path')
    op.drop_column('questions', 'unit_id')
    op.drop_column('question_stats', 'option_counts')
    op.drop_column('question_stats', 'correct_rate')
    op.drop_index('ix_question_reviews_question_created', table_name='question_reviews')
    op.drop_column('question_reviews', 'model')
    op.drop_column('question_reviews', 'checks')
    op.drop_constraint(op.f('fk_question_reports_resolved_by_users'), 'question_reports', type_='foreignkey')
    op.drop_index(op.f('ix_question_reports_resolved_by'), table_name='question_reports')
    op.drop_index('ix_question_reports_open', table_name='question_reports', postgresql_where=sa.text("status = 'pending'"))
    op.drop_column('question_reports', 'resolved_at')
    op.drop_column('question_reports', 'resolved_by')
    op.drop_constraint(op.f('fk_question_concepts_concept_id_concepts'), 'question_concepts', type_='foreignkey')
    op.create_foreign_key(op.f('fk_question_concepts_concept_id_concepts'), 'question_concepts', 'concepts', ['concept_id'], ['id'], ondelete='CASCADE')
    op.drop_column('question_concepts', 'weight')
    op.drop_constraint(op.f('fk_posts_ai_tag_topic_id_topics'), 'posts', type_='foreignkey')
    op.drop_constraint(op.f('fk_posts_author_id_users'), 'posts', type_='foreignkey')
    op.drop_constraint(op.f('fk_posts_unit_id_units'), 'posts', type_='foreignkey')
    op.drop_constraint('fk_posts_accepted_reply_id_replies', 'posts', type_='foreignkey')
    op.create_foreign_key(op.f('fk_posts_author_id_users'), 'posts', 'users', ['author_id'], ['id'], ondelete='CASCADE')
    op.drop_index(op.f('ix_posts_unit_id'), table_name='posts')
    op.drop_index('ix_posts_moderation_status', table_name='posts')
    op.drop_index('ix_posts_group_created', table_name='posts')
    op.drop_index(op.f('ix_posts_ai_tag_topic_id'), table_name='posts')
    op.drop_index(op.f('ix_posts_accepted_reply_id'), table_name='posts')
    # Before 0003 every post needed an author: remove posts whose author was deleted.
    op.execute("DELETE FROM posts WHERE author_id IS NULL")
    op.alter_column('posts', 'author_id',
               existing_type=sa.UUID(),
               nullable=False)
    op.drop_column('posts', 'deleted_at')
    op.drop_column('posts', 'accepted_reply_id')
    op.drop_column('posts', 'reply_count')
    op.drop_column('posts', 'score')
    op.drop_column('posts', 'moderation_reason')
    op.drop_column('posts', 'is_question')
    op.drop_column('posts', 'ai_tag_confidence')
    op.drop_column('posts', 'ai_tag_topic_id')
    op.drop_column('posts', 'image_paths')
    op.drop_column('posts', 'unit_id')
    op.drop_constraint(op.f('fk_plan_items_concept_id_concepts'), 'plan_items', type_='foreignkey')
    op.drop_constraint(op.f('fk_plan_items_recommendation_id_recommendations'), 'plan_items', type_='foreignkey')
    op.drop_index(op.f('ix_plan_items_recommendation_id'), table_name='plan_items')
    op.drop_index(op.f('ix_plan_items_concept_id'), table_name='plan_items')
    op.drop_column('plan_items', 'estimated_minutes')
    op.drop_column('plan_items', 'done_at')
    op.drop_column('plan_items', 'recommendation_id')
    op.drop_column('plan_items', 'concept_id')
    op.drop_column('plan_items', 'action_type')
    op.drop_constraint(op.f('fk_papers_job_id_ai_jobs'), 'papers', type_='foreignkey')
    op.drop_index(op.f('ix_papers_job_id'), table_name='papers')
    op.drop_column('papers', 'job_id')
    op.drop_column('papers', 'prompt_version')
    op.drop_column('papers', 'model')
    op.drop_column('papers', 'blueprint')
    op.drop_column('papers', 'unit_ids')
    op.drop_constraint('uq_paper_questions_paper_question', 'paper_questions', type_='unique')
    op.drop_constraint(op.f('fk_notes_topic_id_topics'), 'notes', type_='foreignkey')
    op.drop_constraint(op.f('fk_notes_job_id_ai_jobs'), 'notes', type_='foreignkey')
    op.drop_constraint(op.f('fk_notes_reviewed_by_users'), 'notes', type_='foreignkey')
    op.drop_constraint(op.f('fk_notes_concept_id_concepts'), 'notes', type_='foreignkey')
    op.create_foreign_key(op.f('fk_notes_topic_id_topics'), 'notes', 'topics', ['topic_id'], ['id'], ondelete='CASCADE')
    op.drop_index('uq_notes_topic_kind_approved', table_name='notes', postgresql_where=sa.text("status = 'approved' AND concept_id IS NULL"))
    op.drop_index(op.f('ix_notes_status'), table_name='notes')
    op.drop_index(op.f('ix_notes_reviewed_by'), table_name='notes')
    op.drop_index(op.f('ix_notes_job_id'), table_name='notes')
    op.drop_index(op.f('ix_notes_concept_id'), table_name='notes')
    op.drop_column('notes', 'job_id')
    op.drop_column('notes', 'model')
    op.drop_column('notes', 'review_comment')
    op.drop_column('notes', 'reviewed_at')
    op.drop_column('notes', 'reviewed_by')
    op.drop_column('notes', 'version')
    op.drop_column('notes', 'source')
    op.drop_column('notes', 'concept_id')
    op.drop_constraint(op.f('fk_model_answers_approved_by_users'), 'model_answers', type_='foreignkey')
    op.drop_index(op.f('ix_model_answers_approved_by'), table_name='model_answers')
    op.drop_column('model_answers', 'approved_at')
    op.drop_column('model_answers', 'approved_by')
    op.drop_index('ix_mistakes_user_open', table_name='mistakes', postgresql_where=sa.text('resolved_at IS NULL'))
    op.drop_index('ix_mistakes_user_concept', table_name='mistakes')
    op.drop_column('mistakes', 'resolved_at')
    op.drop_constraint(op.f('fk_misconceptions_created_by_users'), 'misconceptions', type_='foreignkey')
    op.drop_constraint(op.f('fk_misconceptions_concept_id_concepts'), 'misconceptions', type_='foreignkey')
    op.create_foreign_key(op.f('fk_misconceptions_concept_id_concepts'), 'misconceptions', 'concepts', ['concept_id'], ['id'], ondelete='SET NULL')
    op.drop_index(op.f('ix_misconceptions_created_by'), table_name='misconceptions')
    op.drop_column('misconceptions', 'created_by')
    op.drop_column('misconceptions', 'correction_md')
    op.drop_constraint('uq_mcq_options_question_label', 'mcq_options', type_='unique')
    op.drop_index('uq_mcq_options_one_correct', table_name='mcq_options', postgresql_where=sa.text('is_correct'))
    op.drop_column('mcq_options', 'explanation_md')
    op.drop_column('library_items', 'folder')
    op.drop_index('uq_keywords_point_keyword_lower', table_name='keywords')
    op.drop_constraint(op.f('fk_evaluations_job_id_ai_jobs'), 'evaluations', type_='foreignkey')
    op.drop_constraint(op.f('fk_evaluations_manual_marked_by_users'), 'evaluations', type_='foreignkey')
    op.drop_index(op.f('ix_evaluations_manual_marked_by'), table_name='evaluations')
    op.drop_index(op.f('ix_evaluations_job_id'), table_name='evaluations')
    op.drop_column('evaluations', 'job_id')
    op.drop_column('evaluations', 'model')
    op.drop_column('evaluations', 'manual_marked_at')
    op.drop_column('evaluations', 'manual_marked_by')
    op.drop_column('evaluations', 'manual_marks')
    op.drop_column('evaluations', 'confidence')
    op.drop_column('evaluations', 'semantic_score')
    op.drop_column('evaluations', 'keyword_coverage')
    op.drop_column('evaluations', 'method')
    op.drop_index('ix_email_codes_email_purpose_created', table_name='email_codes')
    op.drop_column('document_chunks', 'embedding_model')
    op.drop_column('document_chunks', 'token_count')
    op.drop_column('content_reports', 'resolved_at')
    op.drop_constraint(op.f('uq_concepts_code'), 'concepts', type_='unique')
    op.drop_index('ix_concepts_embedding_hnsw', table_name='concepts', postgresql_using='hnsw', postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.drop_column('concepts', 'embedding_model')
    op.drop_column('concepts', 'is_outdated')
    op.drop_column('concepts', 'order_index')
    op.drop_column('concepts', 'learning_outcome')
    op.drop_column('concepts', 'code')
    op.drop_column('concept_mastery', 'correct_count')
    op.drop_constraint(op.f('uq_community_groups_slug'), 'community_groups', type_='unique')
    op.drop_column('community_groups', 'member_count')
    op.drop_column('community_groups', 'is_default')
    op.drop_column('community_groups', 'slug')
    op.drop_index('ix_audit_log_target', table_name='audit_log')
    op.drop_index('ix_audit_log_actor_created', table_name='audit_log')
    op.drop_column('audit_log', 'after')
    op.drop_column('audit_log', 'before')
    op.drop_constraint(op.f('fk_attempts_unit_id_units'), 'attempts', type_='foreignkey')
    op.drop_constraint(op.f('fk_attempts_topic_id_topics'), 'attempts', type_='foreignkey')
    op.drop_index('uq_attempts_one_open_diagnostic', table_name='attempts', postgresql_where=sa.text("kind = 'diagnostic' AND status = 'in_progress'"))
    op.drop_index('ix_attempts_user_kind_status', table_name='attempts')
    op.drop_index(op.f('ix_attempts_unit_id'), table_name='attempts')
    op.drop_index(op.f('ix_attempts_topic_id'), table_name='attempts')
    op.drop_column('attempts', 'percentage')
    op.drop_column('attempts', 'max_score')
    op.drop_column('attempts', 'time_limit_minutes')
    op.drop_column('attempts', 'question_ids')
    op.drop_column('attempts', 'topic_id')
    op.drop_column('attempts', 'unit_id')
    op.drop_column('attempts', 'mode')
    op.drop_column('attempts', 'kind')
    op.drop_index('ix_answer_points_embedding_hnsw', table_name='answer_points', postgresql_using='hnsw', postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.drop_column('answer_points', 'embedding_model')
    op.drop_column('answer_points', 'embedding')
    op.drop_column('answer_points', 'is_required')
    op.drop_constraint(op.f('fk_ai_usage_log_user_id_users'), 'ai_usage_log', type_='foreignkey')
    op.drop_index(op.f('ix_ai_usage_log_user_id'), table_name='ai_usage_log')
    op.drop_index('ix_ai_usage_log_user_created', table_name='ai_usage_log')
    op.drop_index('ix_ai_usage_log_operation_created', table_name='ai_usage_log')
    op.drop_index('ix_ai_usage_log_created', table_name='ai_usage_log')
    op.drop_column('ai_usage_log', 'images')
    op.drop_column('ai_usage_log', 'user_id')
    op.drop_index('ix_ai_jobs_status_created', table_name='ai_jobs')
    op.drop_index('ix_ai_jobs_requested_by_created', table_name='ai_jobs')
    op.drop_table('user_settings')
    op.drop_index(op.f('ix_notifications_user_id'), table_name='notifications')
    op.drop_index('ix_notifications_user_created', table_name='notifications')
    op.drop_index('ix_notifications_unread', table_name='notifications', postgresql_where=sa.text('read_at IS NULL'))
    op.drop_table('notifications')
    op.drop_index(op.f('ix_mastery_snapshots_user_id'), table_name='mastery_snapshots')
    op.drop_table('mastery_snapshots')
    op.drop_index(op.f('ix_device_tokens_user_id'), table_name='device_tokens')
    op.drop_table('device_tokens')
    op.drop_index(op.f('ix_app_config_updated_by'), table_name='app_config')
    op.drop_table('app_config')
    # ### end Alembic commands ###
