"""Small YouTube Data API v3 client used by the recommendations service.

This is NOT an AI provider, so it lives in the api (ranking the results goes to the ai_service).
"""

import re
from typing import Any

import httpx

from api.core.config import get_settings

YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
MIN_SECONDS = 3 * 60  # only videos of 3-25 minutes are kept
MAX_SECONDS = 25 * 60

_DURATION_RE = re.compile(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$")


def parse_duration(value: str) -> int | None:
    """ISO 8601 "PT12M30S" -> 750 seconds (None for live streams such as "P0D")."""
    match = _DURATION_RE.match(value or "")
    if match is None:
        return None
    hours, minutes, seconds = (int(g or 0) for g in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def right_length(seconds: int | None) -> bool:
    return seconds is not None and MIN_SECONDS <= seconds <= MAX_SECONDS


async def search_videos(query: str, max_results: int = 10) -> list[dict[str, Any]]:
    """Search YouTube and return videos of 3-25 minutes:
    {video_id, title, description, channel, thumbnail_url, duration_seconds}.

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
        "videoEmbeddable": "true",
        "key": api_key,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(YOUTUBE_SEARCH_URL, params=params)
        response.raise_for_status()
        items = [i for i in response.json().get("items", []) if i.get("id", {}).get("videoId")]
        if not items:
            return []
        # search.list has no durations: one videos.list call returns them for all results.
        details = await client.get(
            YOUTUBE_VIDEOS_URL,
            params={
                "part": "contentDetails",
                "id": ",".join(i["id"]["videoId"] for i in items),
                "key": api_key,
            },
        )
        details.raise_for_status()
    durations = {
        d["id"]: parse_duration(d.get("contentDetails", {}).get("duration", ""))
        for d in details.json().get("items", [])
    }
    videos = []
    for item in items:
        video_id = item["id"]["videoId"]
        seconds = durations.get(video_id)
        if not right_length(seconds):
            continue
        snippet = item["snippet"]
        thumbnails = snippet.get("thumbnails", {})
        thumbnail = (thumbnails.get("medium") or thumbnails.get("default") or {}).get("url")
        videos.append(
            {
                "video_id": video_id,
                "title": snippet.get("title", ""),
                "description": snippet.get("description", ""),
                "channel": snippet.get("channelTitle", ""),
                "thumbnail_url": thumbnail,
                "duration_seconds": seconds,
            }
        )
    return videos
