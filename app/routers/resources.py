from fastapi import APIRouter

router = APIRouter(prefix="/resources", tags=["Resources"])

@router.get("/")
def get_resources(topic: str):
    # Step 4 eke YouTube API danawa
    return {"topic": topic, "resources": []}