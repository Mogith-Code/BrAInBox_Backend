"""Small YouTube Data API v3 client used by the recommendations service. Owner: Udith.

This is NOT an AI provider, so it lives in the api (AI ranking still goes to the ai_service).
"""

from typing import Any

import httpx

from api.core.config import get_settings

YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"


async def search_videos(query: str, max_results: int = 10) -> list[dict[str, Any]]:
    """Search YouTube and return simple dicts: {video_id, title, channel}.

    Returns an empty list when YOUTUBE_API_KEY is not set (so dev/test works offline).
    """
    api_key = get_settings().YOUTUBE_API_KEY
    if not api_key:
        return []

    params: dict[str, str | int] = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "maxResults": max_results,
        "relevanceLanguage": "en",
        "safeSearch": "strict",
        "key": api_key,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(YOUTUBE_SEARCH_URL, params=params)
        response.raise_for_status()
        items = response.json().get("items", [])

    # TODO(Udith): also fetch durations (videos.list) and cache results in `resources`.
    return [
        {
            "video_id": item["id"]["videoId"],
            "title": item["snippet"]["title"],
            "channel": item["snippet"]["channelTitle"],
        }
        for item in items
    ]
