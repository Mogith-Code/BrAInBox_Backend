"""Fast AI calls that answer immediately (no job)."""

from fastapi import APIRouter

from ai_service.pipelines.community import auto_tag
from ai_service.pipelines.questions.explain_answers import explain_answers
from ai_service.schemas.jobs import (
    ExplainMCQRequest,
    KeywordScoreRequest,
    SyncResponse,
    TagPostRequest,
)

router = APIRouter(prefix="/sync", tags=["Sync"])


@router.post("/explain-mcq", response_model=SyncResponse, summary="Explain wrong MCQ answers")
async def explain_mcq(request: ExplainMCQRequest) -> SyncResponse:
    """result = {"explanations": {question_id: "1-2 sentence feedback"}} (may be empty)."""
    explanations = await explain_answers([item.model_dump() for item in request.items])
    return SyncResponse(name="explain-mcq", status="ok", result={"explanations": explanations})


@router.post("/tag-post", response_model=SyncResponse, summary="Suggest tags for a post")
async def tag_post(request: TagPostRequest) -> SyncResponse:
    result = await auto_tag.tag_post(request.title, request.body)
    return SyncResponse(name="tag-post", status="todo", result=result)


@router.post("/keyword-score", response_model=SyncResponse, summary="Quick keyword score")
async def keyword_score(request: KeywordScoreRequest) -> SyncResponse:
    # TODO(Keshomigha): load keywords for the question and use pipelines.evaluation.keyword_match.
    return SyncResponse(name="keyword-score", status="todo")
