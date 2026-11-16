"""Written-answer evaluation, quality gates, misconception mapping, community and resource
pipelines. All run with the fake providers (no API keys, no network)."""

import pytest

from ai_service.errors import UserInputError
from ai_service.pipelines.community import auto_tag, moderation, suggested_answer
from ai_service.pipelines.evaluation import feedback, ocr, scorer
from ai_service.pipelines.evaluation.keyword_match import keyword_hits, normalise, stem
from ai_service.pipelines.evaluation.scorer import coverage, problem_for, structure_check
from ai_service.pipelines.evaluation.semantic_match import cosine, split_sentences
from ai_service.pipelines.questions import mcq_mapping, quality_checks
from ai_service.pipelines.recommendations import rank_resources
from ai_service.providers import get_storage, set_providers
from ai_service.providers.fakes import FakeLLM
from ai_service.schemas.llm_outputs import MisconceptionMappingSet

# --------------------------------------------------------------------------- keyword matching


def test_stemming_matches_word_forms():
    assert stem("mitochondria") == stem("mitochondrion")
    assert stem("diffuses") == stem("diffuse")
    assert stem("cell") == "cell" and stem("atp") == "atp"
    assert normalise("Active Transport!") == [stem("active"), stem("transport")]


def test_keyword_hits_use_stems_synonyms_and_spelling():
    answer = "The mitocondria make ATP. Carrier proteins move the ions."
    assert keyword_hits(answer, ["mitochondrion"]) == ["mitochondrion"]  # one letter missing
    assert keyword_hits(answer, ["carrier protein", "osmosis"]) == ["carrier protein"]
    assert keyword_hits(answer, ["energy"], {"energy": ["ATP"]}) == ["energy"]
    assert keyword_hits(answer, ["ribosome"]) == []


# --------------------------------------------------------------------------- the scoring rule


@pytest.mark.parametrize(
    ("similarity", "keyword", "expected"),
    [
        (0.80, False, ("covered", 1.0)),
        (0.79, False, ("partial", 0.5)),
        (0.65, True, ("covered", 1.0)),  # a keyword lifts a partial match to covered
        (0.65, False, ("partial", 0.5)),
        (0.64, True, ("missing", 0.0)),  # keywords alone are not enough
        (0.10, False, ("missing", 0.0)),
    ],
)
def test_coverage_rule(similarity, keyword, expected):
    assert coverage(similarity, keyword, 0.80, 0.65) == expected


def test_problem_types():
    assert problem_for("covered", True) is None
    assert problem_for("partial", False) == "incomplete"
    assert problem_for("missing", True) == "wrong_application"
    assert problem_for("missing", False) == "missing_concept"


def test_structure_check():
    def result(pid, status, position, required=False):
        return {
            "answer_point_id": pid,
            "status": status,
            "position": position,
            "is_required": required,
        }

    assert structure_check([result("a", "covered", 0), result("b", "covered", 2)])["ok"]
    out = structure_check([result("a", "covered", 3), result("b", "covered", 1)])
    assert out["in_order"] is False
    out = structure_check([result("a", "missing", -1, required=True)])
    assert out["missing_required"] == ["a"] and out["ok"] is False


def test_sentences_and_cosine():
    parts = split_sentences("ATP is used. Ok. Ions move against the gradient\n- carrier proteins")
    assert parts[0] == "ATP is used."
    assert any("carrier proteins" in p for p in parts)
    assert cosine([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert cosine([1.0, 0.0], [0.0, 1.0]) == 0.0


# --------------------------------------------------------------------------- EVALUATE_ANSWER

POINTS = [
    {
        "id": "p1",
        "text": "Active transport moves substances against the concentration gradient",
        "marks": 2,
        "keywords": [{"keyword": "concentration gradient", "synonyms": []}],
    },
    {
        "id": "p2",
        "text": "Energy from ATP is required",
        "marks": 1,
        "keywords": [{"keyword": "ATP", "synonyms": ["adenosine triphosphate"]}],
    },
    {
        "id": "p3",
        "text": "Carrier proteins in the membrane are used",
        "marks": 1,
        "is_required": True,
        "keywords": [{"keyword": "carrier protein", "synonyms": ["pump"]}],
    },
]


@pytest.fixture
def no_rag(monkeypatch):
    async def nothing(*args, **kwargs):
        return []

    monkeypatch.setattr(feedback, "retrieve", nothing)


async def test_full_marks_when_every_point_is_written(no_rag):
    answer = (
        "Active transport moves substances against the concentration gradient. "
        "Energy from ATP is required. Carrier proteins in the membrane are used."
    )
    out = await scorer.run({"question": "Describe active transport.", "answer_text": answer,
                            "max_marks": 4, "points": POINTS})  # fmt: skip
    assert out["estimated_marks"] == 4
    assert [p["status"] for p in out["points"]] == ["covered"] * 3
    assert out["keyword_coverage"] == 1.0
    assert out["structure"]["ok"] is True
    assert out["tips"] == [] and "every marking point" in out["feedback"]


async def test_missing_points_give_tips_and_never_more_than_max(no_rag):
    answer = "Active transport moves substances against the concentration gradient."
    out = await scorer.run({"question": "Describe active transport.", "answer_text": answer,
                            "max_marks": 1, "points": POINTS})  # fmt: skip
    statuses = {p["answer_point_id"]: p["status"] for p in out["points"]}
    assert statuses == {"p1": "covered", "p2": "missing", "p3": "missing"}
    assert out["estimated_marks"] == 1  # 2 marks earned, capped at the question's marks
    assert out["structure"]["missing_required"] == ["p3"]
    assert len(out["tips"]) == 2 and all(t.startswith("Add this point") for t in out["tips"])
    assert out["ai_generated"] is False  # the fake LLM writes no tips: the template is used
    assert out["prompt_version"] == "evaluation/feedback.v2"


async def test_keywords_without_meaning_are_a_wrong_application(no_rag):
    out = await scorer.run(
        {
            "question": "Describe active transport.",
            "answer_text": "ATP is a nucleotide found in every living cell of the body.",
            "points": [POINTS[1]],
        }
    )
    point = out["points"][0]
    assert point["keyword_hit"] is True and point["status"] == "missing"
    assert point["problem"] == "wrong_application"
    assert out["tips"][0].startswith("You used the right terms")


async def test_llm_tips_are_used_but_cannot_change_the_marks(no_rag):
    class TipLLM(FakeLLM):
        async def generate_json(self, prompt, schema, **kwargs):
            assert "Energy from ATP is required" in prompt
            return schema(
                feedback="Good start.", improvements=["Say that ATP supplies the energy."]
            )

    set_providers(llm=TipLLM())
    answer = "Active transport moves substances against the concentration gradient."
    out = await scorer.run({"question": "Q", "answer_text": answer, "points": POINTS[:2]})
    assert out["ai_generated"] is True
    assert out["tips"] == ["Say that ATP supplies the energy."]
    assert out["estimated_marks"] == 2


async def test_empty_answer_and_no_scheme_are_input_errors():
    with pytest.raises(UserInputError) as empty:
        await scorer.run({"answer_text": " ", "points": POINTS})
    with pytest.raises(UserInputError) as no_points:
        await scorer.run({"answer_text": "An answer", "points": []})
    assert (empty.value.code, no_points.value.code) == ("EMPTY_ANSWER", "NO_MARKING_POINTS")


async def test_evaluate_answer_job_route(ai_client, no_rag):
    response = await ai_client.post(
        "/jobs/run",
        json={
            "job_id": "j1",
            "job_type": "evaluate_answer",
            "payload": {"question": "Q", "answer_text": "Energy from ATP is required.",
                        "points": POINTS},
        },
    )  # fmt: skip
    assert response.status_code == 200, response.text
    assert response.json()["result"]["method"] == "hybrid"


# --------------------------------------------------------------------------- OCR_ANSWER


async def test_ocr_reads_every_page():
    storage = get_storage()
    await storage.save("answers/u/1/page-1.jpg", b"first", "image/jpeg")
    await storage.save("answers/u/1/page-2.jpg", b"second page", "image/jpeg")
    out = await ocr.run({"image_paths": ["answers/u/1/page-1.jpg", "answers/u/1/page-2.jpg"]})
    assert [p["page"] for p in out["pages"]] == [1, 2]
    assert out["ocr_text"].count("fake-ocr") == 2


async def test_ocr_input_errors():
    with pytest.raises(UserInputError) as none:
        await ocr.run({"image_paths": []})
    with pytest.raises(UserInputError) as missing:
        await ocr.run({"image_paths": ["answers/u/x/page-1.jpg"]})
    assert (none.value.code, missing.value.code) == ("NO_PAGES", "PAGE_NOT_FOUND")


# --------------------------------------------------------------------------- quality gates

GOOD = {
    "question": "Which organelle is the main site of aerobic respiration?",
    "options": ["Ribosome", "Mitochondrion", "Golgi apparatus", "Lysosome", "Nucleus"],
    "correct_answer": "Mitochondrion",
}


def test_rule_checks():
    assert quality_checks.rule_issues(GOOD) == []
    four = {**GOOD, "options": GOOD["options"][:4]}
    assert any("exactly 5" in i for i in quality_checks.rule_issues(four))
    duplicate = {**GOOD, "options": ["Ribosome", "ribosome ", "Mitochondrion", "A", "B"]}
    assert "Two options are the same." in quality_checks.rule_issues(duplicate)
    no_key = {**GOOD, "correct_answer": "Chloroplast"}
    assert any("Exactly one option" in i for i in quality_checks.rule_issues(no_key))
    catch_all = {**GOOD, "options": [*GOOD["options"][:4], "All of the above"]}
    assert any("not allowed" in i for i in quality_checks.rule_issues(catch_all))
    assert quality_checks.rule_issues({**catch_all, "allow_all_of_above": True}) == []
    assert any("longer" in i for i in quality_checks.rule_issues({**GOOD, "question": "x" * 601}))


async def test_review_rejects_bank_duplicates_and_outdated():
    out = await quality_checks.run(
        {
            "questions": [
                GOOD,
                {**GOOD, "question": "What does the nephron filter?", "outdated": True},
            ],
            "existing": [GOOD["question"]],
        }
    )
    first, second = out["reviews"]
    assert first["passed"] is False and first["checks"]["duplicate"]["similarity"] == 1.0
    assert second["checks"]["duplicate"]["passed"] is True
    assert second["checks"]["syllabus"]["passed"] is False
    assert (out["passed"], out["rejected"]) == (0, 2)


async def test_blind_review_rejects_a_wrong_key(monkeypatch):
    class Reviewer(FakeLLM):
        async def generate_json(self, prompt, schema, **kwargs):
            assert "Mitochondrion" in prompt and "correct_answer" not in prompt
            return schema(answer_index=1, confidence=0.9)

    set_providers(llm=Reviewer())
    monkeypatch.setattr(quality_checks.get_settings(), "USE_FAKE_AI", False)
    monkeypatch.setattr(quality_checks.get_settings(), "GEMINI_API_KEY", "x")
    right = await quality_checks.blind_check(GOOD)
    wrong = await quality_checks.blind_check({**GOOD, "correct_answer": "Nucleus"})
    assert right["passed"] is True
    assert wrong["passed"] is False and wrong["reviewer_answer"] == "Mitochondrion"


# --------------------------------------------------------------------------- misconception mapping


async def test_mapping_reuses_a_similar_existing_misconception():
    known = [{"id": "m-1", "title": "Confuses active transport with facilitated diffusion"}]

    class Mapper(FakeLLM):
        async def generate_json(self, prompt, schema, **kwargs):
            return MisconceptionMappingSet.model_validate(
                {
                    "mappings": [
                        {"option_label": "A", "misconception_id": "m-1"},
                        # the same idea in the same words -> reuse m-1
                        {"option_label": "C", "new_misconception_title": known[0]["title"]},
                        {
                            "option_label": "D",
                            "new_misconception_title": "Thinks osmosis needs ATP",
                        },
                        {"option_label": "B", "misconception_id": "m-1"},  # the correct option
                    ]
                }
            )

    set_providers(llm=Mapper())
    out = await mcq_mapping.run(
        {
            "question": {
                "id": "q1",
                "question": "Which process needs ATP?",
                "options": [
                    {"label": label, "text": f"opt {label}", "is_correct": label == "B"}
                    for label in "ABCD"
                ],
            },
            "misconceptions": known,
        }
    )
    by_label = {m["option_label"]: m for m in out["mappings"]}
    assert set(by_label) == {"A", "C", "D"}  # never the correct option
    assert by_label["A"]["misconception_id"] == "m-1"
    assert by_label["C"]["misconception_id"] == "m-1" and by_label["C"]["similarity"] == 1.0
    assert by_label["D"]["misconception_id"] is None
    assert by_label["D"]["new_misconception_title"] == "Thinks osmosis needs ATP"


# --------------------------------------------------------------------------- community

TOPICS = [
    {"id": "t1", "title": "Cell membrane and transport", "unit_number": 2},
    {"id": "t2", "title": "Mendelian genetics and inheritance", "unit_number": 6},
]


async def test_tag_post_picks_the_closest_topic():
    out = await auto_tag.tag_post("Mendelian inheritance", "How do genetics ratios work?", TOPICS)
    assert (out["topic_id"], out["unit_number"]) == ("t2", 6)
    nothing = await auto_tag.tag_post("zzz", "qqq", TOPICS)
    assert nothing["topic_id"] is None


async def test_tag_post_route(ai_client):
    response = await ai_client.post(
        "/sync/tag-post", json={"title": "Cell membrane transport", "body": "", "topics": TOPICS}
    )
    assert response.json()["status"] == "ok"
    assert response.json()["result"]["topic_id"] == "t1"


async def test_moderation_rules_and_fallback():
    assert (await moderation.moderate("Osmosis", "Can someone explain water potential?"))["allowed"]
    phone = await moderation.moderate("Call me", "my number is 077 123 4567")
    assert phone["label"] == "inappropriate" and phone["categories"] == ["personal_data"]
    spam = await moderation.moderate("", "Join my telegram group and earn money")
    assert spam["allowed"] is False

    class Broken(FakeLLM):
        async def generate_json(self, *args, **kwargs):
            raise RuntimeError("model down")

    set_providers(llm=Broken())
    held = await moderation.moderate("Hi", "A normal question")
    assert held["allowed"] is False and held["categories"] == ["needs_review"]


async def test_moderate_route(ai_client):
    response = await ai_client.post("/sync/moderate", json={"title": "Q", "body": "What is ATP?"})
    assert response.json()["result"]["label"] == "ok"


async def test_suggested_answer_needs_sources(monkeypatch):
    async def nothing(*args, **kwargs):
        return []

    monkeypatch.setattr(suggested_answer, "retrieve", nothing)
    out = await suggested_answer.run({"title": "What is ATP?", "body": ""})
    assert out["body"] is None and out["reason"] == "no_sources"
    assert (await suggested_answer.run({"title": "", "body": ""}))["reason"] == "empty_post"


# --------------------------------------------------------------------------- resources


async def test_rank_resources_drops_weak_matches():
    out = await rank_resources.run(
        {
            "concept": "Active transport",
            "topic": "Cell membrane",
            "candidates": [
                {"id": "a", "title": "Cooking pasta at home", "description": "recipe"},
                {"id": "b", "title": "Active transport explained | A/L Biology cell membrane",
                 "description": "Active transport in the cell membrane"},
            ],
        }
    )  # fmt: skip
    assert [r["id"] for r in out["resources"]] == ["b"]
    assert rank_resources.title_overlap("Active transport", "active transport!") == 1.0


async def test_keyword_score_route(ai_client):
    response = await ai_client.post(
        "/sync/keyword-score",
        json={"answer_text": "ATP is used by carrier proteins", "keywords": ["ATP", "osmosis"]},
    )
    assert response.json()["result"] == {"hits": ["ATP"], "coverage": 0.5}
