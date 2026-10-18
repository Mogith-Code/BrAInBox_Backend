"""Score an answer by matching marking-scheme keywords. Owner: Keshomigha."""


def keyword_hits(answer: str, keywords: list[str]) -> list[str]:
    """Keywords that appear in the answer (case-insensitive). Placeholder logic."""
    # TODO(Keshomigha): stemming, synonyms, spelling tolerance.
    text = answer.lower()
    return [k for k in keywords if k.lower() in text]


# TODO(Keshomigha):
#   - normalise text (lowercase, simple stemming), match keywords + synonyms per answer point
