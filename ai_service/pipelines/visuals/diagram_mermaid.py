"""Check and clean Mermaid code produced by the LLM. Owner: Mogith.

validate_mermaid() is strict on purpose: the code is rendered by Kroki here and again on the
phone, so anything odd is rejected and the pipeline asks the LLM again.
"""

import re

# First word of the diagram. "graph" is the old name of "flowchart".
MERMAID_TYPES = (
    "graph",
    "flowchart",
    "sequenceDiagram",
    "classDiagram",
    "stateDiagram",
    "stateDiagram-v2",
)
MAX_MERMAID_CHARS = 5000

# ```mermaid ... ```  or  ~~~ ... ~~~  around the code
_FENCE_RE = re.compile(r"^\s*(```|~~~)\s*(mermaid)?\s*\n?(?P<code>.*?)\n?\s*(```|~~~)\s*$", re.S)
# Mermaid "click" lines can run links / JavaScript in a browser, so we never allow them.
_CLICK_RE = re.compile(r"^\s*click\s", re.M)


def strip_fences(code: str) -> str:
    """Remove Markdown code fences the LLM sometimes adds."""
    match = _FENCE_RE.match(code)
    return (match.group("code") if match else code).strip()


def validate_mermaid(code: str | None) -> str:
    """Return cleaned Mermaid code or raise ValueError with the reason."""
    cleaned = strip_fences(code or "")
    if not cleaned:
        raise ValueError("Mermaid code is empty")
    if len(cleaned) > MAX_MERMAID_CHARS:
        raise ValueError(f"Mermaid code is longer than {MAX_MERMAID_CHARS} characters")

    # The diagram type is the first word of the first line that is not a %% comment.
    lines = [line.strip() for line in cleaned.splitlines()]
    first = next((line for line in lines if line and not line.startswith("%%")), "")
    diagram_type = first.split()[0] if first.split() else ""
    if diagram_type not in MERMAID_TYPES:
        raise ValueError(f"Not a supported Mermaid diagram type: {diagram_type!r}")
    if _CLICK_RE.search(cleaned):
        raise ValueError("Mermaid 'click' lines are not allowed")
    return cleaned
