"""Fast AI calls that answer immediately (no job)."""

from fastapi import APIRouter

from ai_service.pipelines.community import auto_tag, moderation
from ai_service.pipelines.diagnostic import summary as diagnostic_summary
from ai_service.pipelines.evaluation.keyword_match import keyword_hits
from ai_service.pipelines.home import next_action
from ai_service.pipelines.questions.explain_answers import explain_answers
from ai_service.pipelines.recommendations import rank_resources
from ai_service.schemas.jobs import (
    DiagnosticSummaryRequest,
    ExplainMCQRequest,
    KeywordScoreRequest,
    ModerateRequest,
    NextActionRequest,
    RankResourcesRequest,
    SyncResponse,
    TagPostRequest,
)

router = APIRouter(prefix="/sync", tags=["Sync"])


@router.post("/explain-mcq", response_model=SyncResponse, summary="Explain wrong MCQ answers")
async def explain_mcq(request: ExplainMCQRequest) -> SyncResponse:
    """result = {"explanations": {question_id: "1-2 sentence feedback"}} (may be empty)."""
    explanations = await explain_answers([item.model_dump() for item in request.items])
    return SyncResponse(name="explain-mcq", status="ok", result={"explanations": explanations})


@router.post("/tag-post", response_model=SyncResponse, summary="Suggest the topic of a post")
async def tag_post(request: TagPostRequest) -> SyncResponse:
    """result = {"topic_id", "topic_title", "unit_number", "tags", "confidence"}"""
    result = await auto_tag.tag_post(
        request.title, request.body, [t.model_dump() for t in request.topics]
    )
    return SyncResponse(name="tag-post", status="ok", result=result)


@router.post("/moderate", response_model=SyncResponse, summary="Classify a post or reply")
async def moderate(request: ModerateRequest) -> SyncResponse:
    """result = {"label": ok | off_topic | inappropriate, "allowed", "categories", "reason"}"""
    result = await moderation.moderate(request.title, request.body)
    return SyncResponse(name="moderate", status="ok", result=result)


@router.post("/keyword-score", response_model=SyncResponse, summary="Quick keyword score")
async def keyword_score(request: KeywordScoreRequest) -> SyncResponse:
    """result = {"hits": [...], "coverage": 0..1}. Plain text matching, no AI call."""
    hits = keyword_hits(request.answer_text, request.keywords)
    coverage = len(hits) / len(request.keywords) if request.keywords else 0.0
    return SyncResponse(
        name="keyword-score", status="ok", result={"hits": hits, "coverage": round(coverage, 3)}
    )


@router.post("/rank-resources", response_model=SyncResponse, summary="Rank videos for a concept")
async def rank_resources_route(request: RankResourcesRequest) -> SyncResponse:
    """result = {"resources": [{"id", "score", "reason"}]}, best first; weak matches dropped."""
    resources = await rank_resources.rank(
        request.concept,
        request.topic,
        [c.model_dump() for c in request.candidates],
        request.limit,
    )
    return SyncResponse(name="rank-resources", status="ok", result={"resources": resources})


@router.post(
    "/diagnostic-summary", response_model=SyncResponse, summary="2-sentence diagnostic summary"
)
async def diagnostic_summary_route(request: DiagnosticSummaryRequest) -> SyncResponse:
    """result = {"summary": "...", "prompt_version": "diagnostic/summary.v1"}"""
    result = await diagnostic_summary.summarize(request.model_dump())
    return SyncResponse(name="diagnostic-summary", status="ok", result=result)


@router.post("/next-action", response_model=SyncResponse, summary="Reason for the next best action")
async def next_action_route(request: NextActionRequest) -> SyncResponse:
    """result = {"reason": "...", "prompt_version": "home/next_action.v1"}"""
    result = await next_action.explain(request.model_dump())
    return SyncResponse(name="next-action", status="ok", result=result)
