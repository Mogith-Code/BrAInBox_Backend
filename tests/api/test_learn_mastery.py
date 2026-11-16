"""Learn tab mastery and weak-topic rules (api/modules/learn/mastery.py). Pure, no database."""

import pytest

from api.modules.learn import mastery
from api.modules.learn.mastery import NO_PRACTICE, PracticeStats, TopicMastery
from shared.enums import TopicProgressStatus


def stats(correct: int, total: int, recent_correct: int | None = None, recent_total=None):  # type: ignore[no-untyped-def]
    """Answers with the last-20 window filled like the database query does."""
    recent_total = min(total, 20) if recent_total is None else recent_total
    recent_correct = min(correct, recent_total) if recent_correct is None else recent_correct
    return PracticeStats(total, correct, recent_total, recent_correct)


@pytest.mark.parametrize(
    ("percent", "answers", "level"),
    [
        (0, 0, "weak"),
        (44.9, 5, "weak"),
        (45, 5, "improving"),
        (74, 5, "improving"),
        (75, 5, "strong"),
        (89, 30, "strong"),
        (90, 10, "mastered"),
        (100, 9, "strong"),  # >= 90 needs at least 10 answers
        (95, 0, "strong"),
    ],
)
def test_levels(percent, answers, level):
    assert mastery.level_for(percent, answers) == level


def test_without_practice_reading_counts_half():
    m = mastery.topic_mastery(NO_PRACTICE, progress_percent=80)
    assert (m.mastery_percent, m.level, m.is_weak, m.answers) == (40, "weak", False, 0)
    assert mastery.topic_mastery(NO_PRACTICE, 100).mastery_percent == 50  # never "mastered"


def test_practice_wins_over_reading():
    m = mastery.topic_mastery(stats(correct=7, total=10), progress_percent=100)
    assert (m.mastery_percent, m.level) == (70, "improving")


def test_accuracy_uses_only_the_last_20_answers():
    # 30 answers: the old ones were wrong, the last 20 are 19/20 right.
    m = mastery.topic_mastery(stats(19, 30, recent_correct=19, recent_total=20), 0)
    assert (m.mastery_percent, m.level) == (95, "mastered")


def test_high_accuracy_with_few_answers_is_not_mastered():
    m = mastery.topic_mastery(stats(5, 5), 0)
    assert (m.mastery_percent, m.level) == (100, "strong")


@pytest.mark.parametrize(
    ("correct", "total", "weak"),
    [(0, 2, False), (1, 3, True), (2, 5, True), (5, 10, False), (4, 10, True)],
)
def test_is_weak_needs_3_answers_and_under_50_percent(correct, total, weak):
    assert mastery.topic_mastery(stats(correct, total), 0).is_weak is weak


@pytest.mark.parametrize(
    ("level", "stored", "touched", "expected"),
    [
        ("mastered", None, False, TopicProgressStatus.MASTERED),
        ("strong", TopicProgressStatus.MASTERED, True, TopicProgressStatus.IN_PROGRESS),
        ("weak", None, True, TopicProgressStatus.IN_PROGRESS),
        ("weak", TopicProgressStatus.IN_PROGRESS, False, TopicProgressStatus.IN_PROGRESS),
        ("weak", None, False, TopicProgressStatus.NOT_STARTED),
        ("weak", TopicProgressStatus.NOT_STARTED, False, TopicProgressStatus.NOT_STARTED),
    ],
)
def test_topic_status(level, stored, touched, expected):
    m = TopicMastery(mastery_percent=0, level=level, is_weak=False, answers=0)
    assert mastery.topic_status(m, stored, touched) == expected


def test_unit_mastery_is_the_average_of_its_topics():
    topics = [
        mastery.topic_mastery(stats(10, 10), 0),  # 100, mastered
        mastery.topic_mastery(stats(1, 4), 0),  # 25, weak
        mastery.topic_mastery(NO_PRACTICE, 0),  # 0, not started
    ]
    u = mastery.unit_mastery(topics)
    assert (u.mastery_percent, u.level, u.mastered_count, u.weak_count) == (42, "weak", 1, 1)


def test_unit_is_mastered_only_when_every_topic_is():
    all_mastered = [mastery.topic_mastery(stats(20, 20), 0)] * 3
    assert mastery.unit_mastery(all_mastered).level == "mastered"
    mixed = [*all_mastered, mastery.topic_mastery(stats(9, 10), 0)]  # 90 % with 10 answers
    assert mastery.unit_mastery(mixed).level == "mastered"
    one_strong = [*all_mastered, mastery.topic_mastery(stats(17, 20), 0)]  # 85 strong
    assert mastery.unit_mastery(one_strong).level == "strong"


def test_empty_unit():
    assert mastery.unit_mastery([]) == mastery.UnitMastery(0, "weak", 0, 0)
