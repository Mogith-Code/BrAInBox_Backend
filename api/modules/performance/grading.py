"""Performance thresholds: the ONE place they are defined. Owner: Keshomigha.

The grade bands follow Sri Lankan A/L-style boundaries. They are project-configured
thresholds chosen by the team, not verified official examination regulations, so a
grade here is a practice indicator, never the student's official exam grade.

Change a boundary here and every caller (topic insights, exam weak topics) follows.
"""

from dataclasses import dataclass
from enum import StrEnum

# A topic needs at least this many valid answered questions before we call it a weak area.
MIN_QUESTIONS_FOR_RELIABLE_RESULT = 5


class TopicStatus(StrEnum):
    """How well a student understands one topic."""

    STRONG = "strong"  # A
    GOOD = "good"  # B
    DEVELOPING = "developing"  # C
    WEAK = "weak"  # S
    VERY_WEAK = "very_weak"  # F
    INSUFFICIENT_DATA = "insufficient_data"  # fewer than MIN_QUESTIONS_FOR_RELIABLE_RESULT
    NOT_ATTEMPTED = "not_attempted"  # no valid answers at all


@dataclass(frozen=True)
class GradeBand:
    grade: str  # "A"
    label: str  # "Distinction Pass"
    min_percent: float  # inclusive lower bound
    status: TopicStatus
    understanding: str  # shown to students, e.g. "Strong understanding"


# Highest band first. Each band covers min_percent up to (not including) the band above.
GRADE_BANDS: tuple[GradeBand, ...] = (
    GradeBand("A", "Distinction Pass", 75.0, TopicStatus.STRONG, "Strong understanding"),
    GradeBand("B", "Very Good Pass", 65.0, TopicStatus.GOOD, "Good understanding"),
    GradeBand("C", "Credit Pass", 55.0, TopicStatus.DEVELOPING, "Developing understanding"),
    GradeBand(
        "S", "Ordinary/Simple Pass", 35.0, TopicStatus.WEAK, "Weak understanding; needs improvement"
    ),
    GradeBand("F", "Fail", 0.0, TopicStatus.VERY_WEAK, "Very weak / Fail"),
)

WEAK_STATUSES = frozenset({TopicStatus.WEAK, TopicStatus.VERY_WEAK})


def grade_for(percent: float) -> GradeBand:
    """75 -> A, 74.99 -> B, ... 34.99 -> F. Values outside 0-100 are clamped."""
    for band in GRADE_BANDS:
        if percent >= band.min_percent:
            return band
    return GRADE_BANDS[-1]


def is_weak_percent(percent: float) -> bool:
    """True for grades S and F (below 55 %)."""
    return grade_for(percent).status in WEAK_STATUSES
