"""Check and clean Mermaid code produced by the LLM. Owner: Mogith."""

MERMAID_TYPES = ("graph", "flowchart", "sequenceDiagram", "classDiagram", "stateDiagram")


def validate_mermaid(code: str) -> str:
    """Return cleaned Mermaid code or raise ValueError."""
    # TODO(Mogith): stronger validation (e.g. render with mermaid-cli in CI).
    cleaned = code.strip().removeprefix("```mermaid").removesuffix("```").strip()
    if not cleaned.startswith(MERMAID_TYPES):
        raise ValueError("Not a supported Mermaid diagram")
    return cleaned


# TODO(Mogith):
#   - strip ``` fences, check the first line is a known diagram type, limit size
