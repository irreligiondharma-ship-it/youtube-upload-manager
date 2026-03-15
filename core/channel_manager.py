from __future__ import annotations

from typing import Callable, Dict, List, Optional

FULL_COLUMNS = [
    "video_path",
    "video_id",
    "title",
    "description",
    "tags",
    "category_id",
    "privacy_status",
    "publish_at",
    "thumbnail_path",
    "thumbnail_url",
    "playlist_id",
    "playlist_name",
    "playlist_action",
    "default_language",
    "default_audio_language",
    "self_declared_made_for_kids",
    "embeddable",
    "license",
    "published_at",
    "channel_title",
    "action",
    "status",
    "error_message",
    "uploaded_at",
    "updated_at",
    "account_name",
    "notes",
    "retry_count",
]


def ensure_columns(df):
    for col in FULL_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df


def _chunk(values, size):
    for i in range(0, len(values), size):
        yield values[i : i + size]


def fetch_channel_videos(youtube, progress_callback: Optional[Callable[[int], None]] = None) -> List[Dict[str, str]]:
    channel_resp = youtube.channels().list(part="contentDetails", mine=True).execute()
    items = channel_resp.get("items", [])
    if not items:
        raise RuntimeError("No YouTube channel found for this account.")

    uploads_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

    base_rows: List[Dict[str, str]] = []
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

            base_rows.append(
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
            progress_callback(len(base_rows))

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    # Fetch richer metadata (tags, category, privacy, etc.)
    id_map = {row["video_id"]: row for row in base_rows if row.get("video_id")}
    for chunk in _chunk(list(id_map.keys()), 50):
        details = youtube.videos().list(
            part="snippet,status,contentDetails",
            id=",".join(chunk),
            maxResults=50,
        ).execute()

        for item in details.get("items", []):
            vid = item.get("id", "")
            snippet = item.get("snippet", {})
            status = item.get("status", {})
            row = id_map.get(vid, {})
            row.update(
                {
                    "title": str(snippet.get("title", row.get("title", ""))),
                    "description": str(snippet.get("description", row.get("description", ""))),
                    "tags": ",".join(snippet.get("tags", [])) if snippet.get("tags") else "",
                    "category_id": str(snippet.get("categoryId", "")),
                    "default_language": str(snippet.get("defaultLanguage", "")),
                    "default_audio_language": str(snippet.get("defaultAudioLanguage", "")),
                    "privacy_status": str(status.get("privacyStatus", "")),
                    "license": str(status.get("license", "")),
                    "embeddable": str(status.get("embeddable", "")),
                    "self_declared_made_for_kids": str(status.get("selfDeclaredMadeForKids", "")),
                }
            )

        if progress_callback:
            progress_callback(len(base_rows))

    # Build full row list with all columns
    videos: List[Dict[str, str]] = []
    for row in base_rows:
        full_row = {col: "" for col in FULL_COLUMNS}
        full_row.update(row)
        videos.append(full_row)

    return videos
