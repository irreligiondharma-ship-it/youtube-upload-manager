from __future__ import annotations

from typing import Callable, Dict, List, Optional


def fetch_channel_videos(youtube, progress_callback: Optional[Callable[[int], None]] = None) -> List[Dict[str, str]]:
    channel_resp = youtube.channels().list(part="contentDetails", mine=True).execute()
    items = channel_resp.get("items", [])
    if not items:
        raise RuntimeError("No YouTube channel found for this account.")

    uploads_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

    videos: List[Dict[str, str]] = []
    page_token = None
    while True:
        response = youtube.playlistItems().list(
            part="snippet,contentDetails",
            playlistId=uploads_id,
            maxResults=50,
            pageToken=page_token,
        ).execute()

        for item in response.get("items", []):
            snippet = item.get("snippet", {})
            content = item.get("contentDetails", {})
            thumbnails = snippet.get("thumbnails", {})
            thumb_url = (
                thumbnails.get("high", {}).get("url")
                or thumbnails.get("medium", {}).get("url")
                or thumbnails.get("default", {}).get("url")
                or ""
            )

            videos.append(
                {
                    "video_id": str(content.get("videoId", "")),
                    "title": str(snippet.get("title", "")),
                    "description": str(snippet.get("description", "")),
                    "published_at": str(snippet.get("publishedAt", "")),
                    "thumbnail_url": thumb_url,
                    "channel_title": str(snippet.get("channelTitle", "")),
                }
            )

        if progress_callback:
            progress_callback(len(videos))

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return videos
