"""Find marking-scheme keywords in a student's answer.

The answer and the keywords are normalised the same way (lowercase, light stemming), so
"mitochondria" matches "mitochondrion" and "diffuses" matches "diffusion". A keyword also counts
when one of its synonyms is found, or when a long word is misspelt by a letter or two.
No AI call: this is plain text matching.
"""

import re
from difflib import SequenceMatcher

_WORD_RE = re.compile(r"[a-z0-9]+")

# Longest first, so "isation" is removed before "ation" and "s".
_SUFFIXES = (
    "isation", "ization", "ations", "ation", "ities", "ments", "ively", "ingly",
    "ness", "ment", "ions", "ing", "ion", "ies", "ive", "ity", "ous", "ed", "es", "ly", "al",
    "a", "um", "us", "on", "s", "e", "y",
)  # fmt: skip
MIN_STEM = 4  # never cut a word below 4 letters ("gene", "cell", "ATP" stay whole)
FUZZY_MIN_LENGTH = 6  # spelling tolerance only for long words
FUZZY_RATIO = 0.86


def stem(word: str) -> str:
    """A light stemmer for biology terms: strips one common ending, keeps at least 4 letters."""
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= MIN_STEM:
            word = word[: -len(suffix)]
            break
    # Latin plurals: "mitochondri(a)" / "mitochondr(ion)", "nucle(i)" / "nucle(us)"
    if word.endswith("i") and len(word) - 1 >= MIN_STEM:
        word = word[:-1]
    return word


def normalise(text: str) -> list[str]:
    """Lowercase word stems of `text`, in order."""
    return [stem(word) for word in _WORD_RE.findall(text.lower())]


def _contains(answer_stems: list[str], phrase_stems: list[str]) -> bool:
    """True if the phrase's stems appear next to each other in the answer (spelling-tolerant)."""
    size = len(phrase_stems)
    if size == 0:
        return False
    for start in range(len(answer_stems) - size + 1):
        if all(_same(answer_stems[start + i], phrase_stems[i]) for i in range(size)):
            return True
    return False


def _same(a: str, b: str) -> bool:
    if a == b:
        return True
    if min(len(a), len(b)) < FUZZY_MIN_LENGTH:
        return False
    return SequenceMatcher(None, a, b).ratio() >= FUZZY_RATIO


def keyword_hits(
    answer: str, keywords: list[str], synonyms: dict[str, list[str]] | None = None
) -> list[str]:
    """The keywords found in the answer (directly or through a synonym), in the given order."""
    answer_stems = normalise(answer)
    found = []
    for keyword in keywords:
        variants = [keyword, *(synonyms or {}).get(keyword, [])]
        if any(_contains(answer_stems, normalise(v)) for v in variants):
            found.append(keyword)
    return found


def keyword_coverage(answer: str, keywords: list[str]) -> float:
    """Share (0..1) of the keywords that appear in the answer; 0 when there are no keywords."""
    if not keywords:
        return 0.0
    return len(keyword_hits(answer, keywords)) / len(keywords)
