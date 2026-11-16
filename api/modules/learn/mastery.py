"""Mastery and weak-topic rules for the Learn tab. ONE place for every rule. Owner: Samni.

Inputs per topic and student:
  * practice: answers to practice/quiz/exam questions of the topic (responses.is_correct,
    via attempts -> responses -> questions.topic_id). Read from the existing tables.
  * reading:  user_topic_progress.progress_percent (POST /learn/topics/{id}/progress)

Rules:
  * mastery_percent = accuracy over the LAST 20 answers, when the student has answered any;
    otherwise progress_percent x 0.5 (reading counts less than practice)
  * level: < 45 weak | 45-74 improving | 75-89 strong | >= 90 AND >= 10 answers mastered
    (>= 90 with fewer than 10 answers stays "strong")
  * is_weak = at least 3 answers and accuracy (last 20) below 50 %
  * topic status = mastered when the level is mastered; otherwise in_progress when the student
    opened/read it or practised it; otherwise not_started
  * unit mastery = average mastery_percent of its topics (untouched topics count as 0);
    the unit level uses the same thresholds with the unit's total answers
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from shared.enums import TopicProgressStatus

RECENT_ANSWERS = 20  # accuracy window
READING_WEIGHT = 0.5  # reading progress counts half
IMPROVING_FROM = 45
STRONG_FROM = 75
MASTERED_FROM = 90
MASTERED_MIN_ANSWERS = 10
WEAK_MIN_ANSWERS = 3
WEAK_BELOW = 50

MasteryLevel = Literal["weak", "improving", "strong", "mastered"]


@dataclass(frozen=True)
class PracticeStats:
    """A student's answers on one topic."""

    total: int = 0  # every answer ever
    correct: int = 0  # correct answers ever
    recent_total: int = 0  # answers among the last RECENT_ANSWERS
    recent_correct: int = 0
    last_answered_at: datetime | None = None

    @property
    def recent_accuracy(self) -> float:
        return 100 * self.recent_correct / self.recent_total if self.recent_total else 0.0

    @property
    def accuracy(self) -> float:
        return 100 * self.correct / self.total if self.total else 0.0


NO_PRACTICE = PracticeStats()


@dataclass(frozen=True)
class TopicMastery:
    mastery_percent: int
    level: MasteryLevel
    is_weak: bool
    answers: int  # how many practice answers this is based on (0 = from reading only)


def level_for(percent: float, answers: int) -> MasteryLevel:
    if percent >= MASTERED_FROM and answers >= MASTERED_MIN_ANSWERS:
        return "mastered"
    if percent >= STRONG_FROM:
        return "strong"
    if percent >= IMPROVING_FROM:
        return "improving"
    return "weak"


def topic_mastery(practice: PracticeStats, progress_percent: int) -> TopicMastery:
    if practice.recent_total > 0:
        percent = practice.recent_accuracy
    else:
        percent = max(0, min(100, progress_percent)) * READING_WEIGHT
    is_weak = practice.total >= WEAK_MIN_ANSWERS and practice.recent_accuracy < WEAK_BELOW
    return TopicMastery(
        mastery_percent=round(percent),
        level=level_for(percent, practice.total),
        is_weak=is_weak,
        answers=practice.total,
    )


def topic_status(
    mastery: TopicMastery, stored: TopicProgressStatus | None, touched: bool
) -> TopicProgressStatus:
    """`stored` = user_topic_progress.status (None = no row). `touched` = opened, read or
    practised at least once."""
    if mastery.level == "mastered":
        return TopicProgressStatus.MASTERED
    if touched or stored in (TopicProgressStatus.IN_PROGRESS, TopicProgressStatus.MASTERED):
        return TopicProgressStatus.IN_PROGRESS
    return TopicProgressStatus.NOT_STARTED


@dataclass(frozen=True)
class UnitMastery:
    mastery_percent: int
    level: MasteryLevel
    mastered_count: int
    weak_count: int


def unit_mastery(topics: list[TopicMastery]) -> UnitMastery:
    """Average of the unit's topics. A unit without topics is 0 / weak."""
    if not topics:
        return UnitMastery(0, "weak", 0, 0)
    average = sum(t.mastery_percent for t in topics) / len(topics)
    answers = sum(t.answers for t in topics)
    # A unit is "mastered" only when every topic is (not just a high average).
    level = level_for(average, answers)
    if level == "mastered" and any(t.level != "mastered" for t in topics):
        level = "strong"
    return UnitMastery(
        mastery_percent=round(average),
        level=level,
        mastered_count=sum(1 for t in topics if t.level == "mastered"),
        weak_count=sum(1 for t in topics if t.is_weak),
    )
