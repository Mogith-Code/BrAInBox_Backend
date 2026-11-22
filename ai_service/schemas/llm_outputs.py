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
class VisualLabel(BaseModel):
    """One numbered label. x / y = where the marker goes, as 0-1 fractions of the image
    (only for illustrations; null for Mermaid visuals, the app lists those under the diagram)."""

    number: int
    name: str
    description: str = ""  # 1-2 short sentences at A/L level
    x: float | None = None
    y: float | None = None


class VisualDecision(BaseModel):
    kind: Literal["diagram", "flowchart", "table", "illustration"]
    title: str
    mermaid_code: str | None = None
    image_prompt: str | None = None
    reason: str = ""
    # Added for prompt decide_visual.v2.
    # Required (no default), so a missing answer never counts as "safe".
    is_biology: bool  # False = the request is not about Biology study -> refused
    alt_text: str = ""  # one sentence read by TalkBack
    labels: list[VisualLabel] = Field(default_factory=list)

    @classmethod
    def fake_example(cls) -> dict[str, Any]:
        """Valid sample used by the fake LLM (offline / tests): a small Mermaid flowchart."""
        return {
            "kind": "diagram",
            "title": "Osmosis across a membrane",
            "mermaid_code": (
                "flowchart LR\n"
                '  A["1. Dilute solution<br/>high water potential"] --> '
                'B["2. Partially permeable membrane"]\n'
                '  B --> C["3. Concentrated solution<br/>low water potential"]'
            ),
            "image_prompt": None,
            "reason": "A structure is clearest as a labelled diagram.",
            "is_biology": True,
            "alt_text": "Water moves from a dilute to a concentrated solution through a membrane.",
            "labels": [
                {
                    "number": 1,
                    "name": "Dilute solution",
                    "description": "Has more free water molecules, so its water potential is higher.",
                },
                {
                    "number": 2,
                    "name": "Partially permeable membrane",
                    "description": "Lets water molecules through but stops larger solute molecules.",
                },
                {
                    "number": 3,
                    "name": "Concentrated solution",
                    "description": "Water moves into it by osmosis, down the water potential gradient.",
                },
            ],
        }


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


class GeneratedMarkingPoint(BaseModel):
    """One marking point of a generated structured / essay question."""

    text: str
    marks: int = Field(ge=1, le=10)
    keywords: list[str] = Field(default_factory=list)  # words that show the point was made


class GeneratedWrittenQuestion(BaseModel):
    """One A/L structured or essay question with its model answer and marking points."""

    question: str
    marks: int = Field(ge=1, le=20)
    model_answer: str
    points: list[GeneratedMarkingPoint] = Field(min_length=1, max_length=15)

    @model_validator(mode="after")
    def points_add_up_to_the_marks(self) -> "GeneratedWrittenQuestion":
        total = sum(p.marks for p in self.points)
        if total != self.marks:
            raise ValueError(f"the marking points give {total} marks, the question {self.marks}")
        return self


class TutorAnswer(BaseModel):
    """Ask BrAInBox: an answer taken from the numbered source passages."""

    answer: str = Field(min_length=1, max_length=4000)
    found_in_sources: bool
    used_sources: list[int] = Field(default_factory=list)

    @classmethod
    def fake_example(cls) -> dict[str, object]:
        return {
            "answer": "Fake answer from the sources.",
            "found_in_sources": True,
            "used_sources": [1],
        }


class GeneratedWrittenSet(BaseModel):
    questions: list[GeneratedWrittenQuestion]

    @classmethod
    def fake_example(cls) -> dict[str, Any]:
        """Valid sample used by the fake LLM (offline / tests)."""
        return {
            "questions": [
                {
                    "question": "Explain how the structure of a mitochondrion suits its function.",
                    "marks": 4,
                    "model_answer": (
                        "The inner membrane is folded into cristae, giving a large surface for "
                        "the electron transport chain and ATP synthase. The matrix holds the "
                        "enzymes of the Krebs cycle."
                    ),
                    "points": [
                        {"text": "Cristae give a large surface area", "marks": 1,
                         "keywords": ["cristae", "surface area"]},
                        {"text": "Electron transport chain / ATP synthase on the inner membrane",
                         "marks": 1, "keywords": ["electron transport", "ATP synthase"]},
                        {"text": "Matrix contains Krebs cycle enzymes", "marks": 1,
                         "keywords": ["matrix", "Krebs"]},
                        {"text": "Double membrane separates the matrix from the cytoplasm",
                         "marks": 1, "keywords": ["double membrane"]},
                    ],
                }
            ]
        }  # fmt: skip


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


class BlindAnswer(BaseModel):
    """A reviewer's own answer to an MCQ, given without the key (quality gate)."""

    answer_index: int = Field(ge=0, le=4)
    confidence: float = Field(ge=0, le=1, default=0.5)


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

    @classmethod
    def fake_example(cls) -> dict[str, Any]:
        """The fake LLM writes no tips, so the pipeline's template tips are used."""
        return {"feedback": "", "strengths": [], "improvements": []}


# ----------------------------------------------------------------- community (Mogith)
class ModerationResult(BaseModel):
    allowed: bool
    label: Literal["ok", "off_topic", "inappropriate"] = "ok"
    categories: list[str] = Field(default_factory=list)
    reason: str = ""

    @model_validator(mode="after")
    def label_and_allowed_agree(self) -> "ModerationResult":
        # Older prompts only answer `allowed`: a refused post is at least "inappropriate".
        if not self.allowed and self.label == "ok":
            self.label = "inappropriate"
        self.allowed = self.label == "ok"
        return self

    @classmethod
    def fake_example(cls) -> dict[str, Any]:
        """The fake LLM lets everything through (the rule checks still run)."""
        return {"allowed": True, "label": "ok", "categories": [], "reason": ""}


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
