"""Structured outputs expected from the LLM, one model per prompt (placeholders).

Owners refine their own models; keep fields simple (str, int, float, bool, lists, nested models)
so Gemini's response_schema can express them.
"""

from typing import Literal

from pydantic import BaseModel, Field


# ----------------------------------------------------------------- notes (Samni)
class GeneratedNotes(BaseModel):
    title: str
    body_md: str
    key_terms: list[str] = Field(default_factory=list)
    cited_refs: list[int] = Field(default_factory=list)  # [n] numbers used from the context


# ----------------------------------------------------------------- visuals (Mogith)
class VisualDecision(BaseModel):
    kind: Literal["diagram", "flowchart", "table", "illustration"]
    title: str
    mermaid_code: str | None = None
    image_prompt: str | None = None
    reason: str = ""


# ----------------------------------------------------------------- questions (Udith)
class GeneratedOption(BaseModel):
    label: str
    text: str
    is_correct: bool
    misconception: str | None = None


class GeneratedMCQ(BaseModel):
    stem: str
    options: list[GeneratedOption]
    explanation: str
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    cited_refs: list[int] = Field(default_factory=list)


class GeneratedMCQSet(BaseModel):
    questions: list[GeneratedMCQ]


class MCQReview(BaseModel):
    verdict: Literal["accept", "revise", "reject"]
    score: float = Field(ge=0, le=10, default=0)
    issues: list[str] = Field(default_factory=list)
    suggested_fix: str | None = None


class MisconceptionMapping(BaseModel):
    option_label: str
    misconception_id: str | None = None
    new_misconception_title: str | None = None


class MisconceptionMappingSet(BaseModel):
    mappings: list[MisconceptionMapping]


# ----------------------------------------------------------------- evaluation (Keshomigha)
class EvaluationFeedback(BaseModel):
    feedback: str
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)


# ----------------------------------------------------------------- community (Mogith)
class ModerationResult(BaseModel):
    allowed: bool
    categories: list[str] = Field(default_factory=list)
    reason: str = ""


class PostTags(BaseModel):
    tags: list[str]
    unit_number: int | None = None
