"""Split long uploads into parts that fit the LLM context."""


def split_for_summary(text: str, max_words: int = 1500) -> list[str]:
    """Split text into parts of at most `max_words` words."""
    words = text.split()
    return [" ".join(words[i : i + max_words]) for i in range(0, len(words), max_words)] or [""]
