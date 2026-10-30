"""Structured outputs expected from the LLM, one model per prompt (placeholders).

Owners refine their own models; keep fields simple (str, int, float, bool, lists, nested models)
so Gemini's response_schema can express them.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


# ----------------------------------------------------------------- notes (Samni)
class GeneratedNotes(BaseModel):
    title: str
    body_md: str
    key_terms: list[str] = Field(default_factory=list)
    cited_refs: list[int] = Field(default_factory=list)  # [n] numbers used from the context


# ----------------------------------------------------------------- summarization (Samni)
class TopicSummary(BaseModel):
    """Revision summary of one topic, built from the student's notes or approved sources."""

    title: str
    body_md: str  # the summary itself, in Markdown (stored in summaries.body_md)
    key_points: list[str] = Field(default_factory=list)  # 3-7 short bullet points
    key_terms: list[str] = Field(default_factory=list)  # Biology terms the student must know


# ----------------------------------------------------------------- visuals (Mogith)
class VisualDecision(BaseModel):
    kind: Literal["diagram", "flowchart", "table", "illustration"]
    title: str
    mermaid_code: str | None = None
    image_prompt: str | None = None
    reason: str = ""


# ----------------------------------------------------------------- questions (Udith)
class GeneratedMCQ(BaseModel):
    """One A/L-style MCQ, in the format of Udith's original generator."""

    question: str
    options: list[str] = Field(min_length=4, max_length=5)
    correct_answer: str  # copied exactly from one of the options
    explanation: str = ""
    marks: int = 1

    @model_validator(mode="after")
    def answer_must_be_in_options(self) -> "GeneratedMCQ":
        if self.correct_answer not in self.options:
            raise ValueError(f"correct_answer {self.correct_answer!r} is not one of the options")
        return self


class GeneratedMCQSet(BaseModel):
    questions: list[GeneratedMCQ]

    @classmethod
    def fake_example(cls) -> dict[str, Any]:
        """Valid sample used by the fake LLM (offline / tests)."""
        return {
            "questions": [
                {
                    "question": "Which organelle is the main site of aerobic respiration?",
                    "options": [
                        "Ribosome",
                        "Mitochondrion",
                        "Golgi apparatus",
                        "Lysosome",
                        "Nucleus",
                    ],
                    "correct_answer": "Mitochondrion",
                    "explanation": "The Krebs cycle and oxidative phosphorylation happen there.",
                    "marks": 1,
                }
            ]
        }


class AnswerExplanation(BaseModel):
    question_id: str
    explanation: str


class AnswerExplanationSet(BaseModel):
    """Short feedback for each wrong / unanswered MCQ (Udith's explainer)."""

    items: list[AnswerExplanation]


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


# ----------------------------------------------------------------- diagnostic (Udith)
class DiagnosticSummary(BaseModel):
    """2 short sentences about the student's diagnostic result."""

    summary: str = Field(min_length=10, max_length=400)

    @classmethod
    def fake_example(cls) -> dict[str, Any]:
        """Deterministic text for the fake LLM (offline / tests)."""
        return {
            "summary": "Fake AI summary: you have a clear strongest unit and one unit that "
            "needs the most work. Your plan starts with the unit that needs work."
        }


# ----------------------------------------------------------------- home (Samni)
class NextActionReason(BaseModel):
    """One short sentence: why this is the best thing to study next."""

    reason: str = Field(min_length=10, max_length=200)

    @classmethod
    def fake_example(cls) -> dict[str, Any]:
        """Deterministic text for the fake LLM (offline / tests)."""
        return {"reason": "Fake AI reason: this is your weakest unit right now."}
