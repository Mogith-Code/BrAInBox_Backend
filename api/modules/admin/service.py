"""Admin-only business logic.

Most admin routes call the service of the module that owns the data
(e.g. `api.modules.questions.service`). Only truly admin-specific code lives here:
the `audit_log` ("who did what in the admin portal") and the dashboard, which combines
several modules.
"""

from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from api.core import clock
from api.core.security import CurrentUser
from api.modules.admin import repository
from api.modules.admin.schemas import (
    DashboardActivity,
    DashboardKpi,
    DashboardMissedTopic,
    DashboardOut,
    DashboardReport,
)
from api.modules.community import service as community_service
from api.modules.community.schemas import ModerationItemOut
from api.modules.content import service as content_service
from api.modules.performance import service as performance_service
from api.modules.profiles import service as profiles_service
from api.modules.quality import service as quality_service
from shared.db.models import AuditLog


async def record_audit(
    session: AsyncSession,
    admin: CurrentUser,
    action: str,
    target_type: str,
    target_id: Any,
    details: dict[str, Any] | None = None,
) -> None:
    """Add one audit_log row, e.g. ("user.suspend", "user", <id>). Commits."""
    await repository.insert_audit_entry(
        session,
        AuditLog(
            actor_id=admin.id,
            action=action,
            target_type=target_type,
            target_id=str(target_id),
            details=details or {},
        ),
    )
    await session.commit()


# =========================================================================== dashboard
# GET /admin/dashboard: one screen built from other modules' services (no SQL here).

SPARKLINE_DAYS = 8
ACTIVITY_DAYS = 14
MISSED_TOPICS = 5
MISSED_PERIOD_DAYS = 30
RECENT_REPORTS = 5
REVIEW_WAIT = timedelta(hours=48)
REASONS = {
    "spam": "Spam",
    "offensive": "Offensive",
    "wrong_info": "Wrong information",
    "off_topic": "Off-topic",
    "wrong_label": "Wrong label on",
    "inaccurate": "Inaccurate",
    "unclear": "Unclear",
    "other": "Reported",
}
TARGET_NAMES = {"post": "post", "reply": "reply", "visual": "diagram"}


def day_labels(days: list[date]) -> list[str]:
    """Pure: "24 Sep", "25", ..., "30", "1 Oct", "2" - the month only on the first day and on
    the 1st of a month."""
    return [
        f"{d.day} {d.strftime('%b')}" if i == 0 or d.day == 1 else str(d.day)
        for i, d in enumerate(days)
    ]


def series(counts: dict[date, int], days: list[date]) -> list[int]:
    return [counts.get(d, 0) for d in days]


def percent_delta(current: int, previous: int, period: str) -> tuple[str, str]:
    """(text, trend) for a change compared with the period before."""
    if previous == 0:
        return ("New this " + period if current else "No change"), "good"
    change = 100 * (current - previous) / previous
    return f"{change:+.1f}% vs last {period}", "good" if change >= 0 else "bad"


def report_card(item: ModerationItemOut) -> DashboardReport:
    """Pure: one open moderation item as a "recent reports" row."""
    reason = REASONS.get(item.reason, item.reason.replace("_", " ").capitalize())
    title = f"{reason} {TARGET_NAMES[item.target_type]}"
    if item.target_type == "visual":
        subtitle = item.visual_title or "Diagram"
    elif item.group_name:
        subtitle = f"Group · {item.group_name}"
    else:
        subtitle = f"{item.target_type.capitalize()} by {item.author_handle or 'a student'}"
    score = item.ai_flag_score or 0.0
    meta = (
        "AI flagged"
        if item.report_count == 1 and score >= 0.8
        else f"{item.report_count} report{'s' if item.report_count != 1 else ''}"
    )
    if item.report_count >= 3 or score >= 0.9 or item.reason == "offensive":
        severity: str | None = "high"
    elif item.report_count == 2 or score >= 0.7:
        severity = "medium"
    else:
        severity = None
    return DashboardReport(title=title, subtitle=subtitle, meta=meta, severity=severity)  # type: ignore[arg-type]


async def build_dashboard(session: AsyncSession, base_url: str) -> DashboardOut:
    today = clock.today()
    spark_days = [today - timedelta(days=n) for n in range(SPARKLINE_DAYS - 1, -1, -1)]
    activity_days = [today - timedelta(days=n) for n in range(ACTIVITY_DAYS - 1, -1, -1)]
    since = activity_days[0]
    since_at = datetime.combine(since, time.min, tzinfo=clock.SRI_LANKA)

    # --- students active in the last 7 days (vs the 7 before)
    week_start = today - timedelta(days=6)
    active = await performance_service.active_students(session, week_start, today)
    before = await performance_service.active_students(
        session, week_start - timedelta(days=7), week_start - timedelta(days=1)
    )
    daily_active = await performance_service.daily_active(session, spark_days[0])
    students_delta, students_trend = percent_delta(active, before, "week")

    # --- quizzes / papers finished today (vs yesterday)
    attempts = await performance_service.daily_finished_attempts(session, since)
    today_attempts, yesterday_attempts = (
        attempts.get(today, 0),
        attempts.get(today - timedelta(days=1), 0),
    )

    # --- AI items waiting for review
    older_than = clock.now() - REVIEW_WAIT
    questions_waiting, questions_old = await quality_service.pending_counts(session, older_than)
    content_waiting, content_old = await content_service.pending_review_counts(session, older_than)
    old = questions_old + content_old
    ai_made = await quality_service.ai_questions_per_day(session, since_at)
    notes_made = await content_service.notes_made_per_day(session, since_at)

    # --- open moderation reports
    queue = await community_service.moderation_queue(session, base_url)
    new_reports = await community_service.reports_per_day(session, since_at)
    report_diff = new_reports.get(today, 0) - new_reports.get(today - timedelta(days=1), 0)

    kpis = [
        DashboardKpi(
            kind="students",
            label="Active students",
            value=active,
            delta=students_delta,
            trend=students_trend,  # type: ignore[arg-type]
            sparkline=series(daily_active, spark_days),
        ),
        DashboardKpi(
            kind="quizzes",
            label="Quizzes taken today",
            value=today_attempts,
            delta=f"{today_attempts - yesterday_attempts:+d} vs yesterday",
            trend="good" if today_attempts >= yesterday_attempts else "bad",
            sparkline=series(attempts, spark_days),
        ),
        DashboardKpi(
            kind="aiReview",
            label="AI items pending review",
            value=questions_waiting + content_waiting,
            delta=f"{old} older than 48h" if old else "None older than 48h",
            trend="warning" if old else "good",
            sparkline=[
                a + b
                for a, b in zip(
                    series(ai_made, spark_days), series(notes_made, spark_days), strict=True
                )
            ],
        ),
        DashboardKpi(
            kind="reports",
            label="Reported posts",
            value=len(queue),
            delta=f"{report_diff:+d} vs yesterday",
            trend="good" if report_diff <= 0 else "bad",
            sparkline=series(new_reports, spark_days),
        ),
    ]

    # --- most missed topics (last 30 days), with the most chosen misconception
    performance = await performance_service.analytics_performance(session, MISSED_PERIOD_DAYS)
    missed = performance.most_missed_topics[:MISSED_TOPICS]
    period_start = today - timedelta(days=MISSED_PERIOD_DAYS - 1)
    top = await performance_service.top_misconceptions(
        session, period_start, [m.topic_id for m in missed]
    )

    newest = sorted(queue, key=lambda i: i.created_at, reverse=True)[:RECENT_REPORTS]
    return DashboardOut(
        batch_label=f"A/L {await profiles_service.main_batch_year(session)} batch",
        kpis=kpis,
        activity=DashboardActivity(
            day_labels=day_labels(activity_days),
            quizzes=series(attempts, activity_days),
            notes_generated=series(notes_made, activity_days),
        ),
        recent_reports=[report_card(i) for i in newest],
        missed_topics_attempts=await performance_service.answers_since(session, period_start),
        missed_topics=[
            DashboardMissedTopic(
                topic=m.topic,
                unit=f"Unit {m.unit_number} · {m.unit}",
                miss_rate=round(m.wrong / m.answers, 2) if m.answers else 0.0,
                attempts=m.answers,
                top_misconception=top.get(m.topic_id, ""),
            )
            for m in missed
        ],
    )
