import logging
import os
import re
import shutil
from typing import Dict, Iterable, List, Optional
from urllib.parse import urlparse
from urllib.request import urlopen

import pandas as pd

from core.excel_manager import REQUIRED_COLUMNS
from core.path_utils import normalize_path


_CHANNEL_ID_RE = re.compile(r"(UC[a-zA-Z0-9_-]{20,})")
_HANDLE_RE = re.compile(r"@([A-Za-z0-9_.-]+)")
_INVALID_PATH_CHARS = re.compile(r'[<>:"/\\\\|?*]+')


def sanitize_filename(value: str, max_len: int = 80) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "untitled"

    cleaned = _INVALID_PATH_CHARS.sub("_", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.strip(". ")

    if not cleaned:
        cleaned = "untitled"

    reserved = {
        "CON", "PRN", "AUX", "NUL",
        "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
    }
    if cleaned.upper() in reserved:
        cleaned = f"_{cleaned}"

    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip()

    return cleaned or "untitled"


def _chunk(values: Iterable[str], size: int) -> Iterable[List[str]]:
    values = list(values)
    for i in range(0, len(values), size):
        yield values[i : i + size]


def resolve_channel_id(youtube, channel_input: str) -> str:
    text = str(channel_input or "").strip()
    if not text:
        raise ValueError("Channel input is empty.")

    match = _CHANNEL_ID_RE.search(text)
    if match:
        return match.group(1)

    handle = None
    handle_match = _HANDLE_RE.search(text)
    if handle_match:
        handle = handle_match.group(1)

    username_candidate = None
    try:
        parsed = urlparse(text)
        path = parsed.path.strip("/") if parsed.scheme else text.strip("/")
        parts = [p for p in path.split("/") if p]
        if parts:
            last = parts[-1]
            if last and not last.startswith("@") and not last.startswith("UC"):
                username_candidate = last
    except Exception:
        username_candidate = None

    if handle:
        try:
            resp = youtube.channels().list(part="id", forHandle=handle).execute()
            items = resp.get("items", [])
            if items:
                return items[0]["id"]
        except Exception:
            pass

    if username_candidate:
        try:
            resp = youtube.channels().list(part="id", forUsername=username_candidate).execute()
            items = resp.get("items", [])
            if items:
                return items[0]["id"]
        except Exception:
            pass

    query = handle or username_candidate or text
    try:
        resp = youtube.search().list(part="snippet", q=query, type="channel", maxResults=1).execute()
        items = resp.get("items", [])
        if items:
            channel_id = items[0].get("id", {}).get("channelId", "")
            if channel_id:
                return channel_id
    except Exception as err:
        logging.warning("Channel search failed: %s", err)

    raise ValueError("Unable to resolve channel ID from input.")


def fetch_playlists(youtube, channel_id: str) -> List[Dict[str, str]]:
    playlists: List[Dict[str, str]] = []
    page_token = None

    try:
        channel_resp = youtube.channels().list(part="contentDetails", id=channel_id).execute()
        items = channel_resp.get("items", [])
        if items:
            uploads_id = (
                items[0]
                .get("contentDetails", {})
                .get("relatedPlaylists", {})
                .get("uploads", "")
            )
            if uploads_id:
                playlists.append(
                    {
                        "id": uploads_id,
                        "title": "Uploads (All Videos)",
                        "item_count": "",
                    }
                )
    except Exception:
        pass

    while True:
        resp = youtube.playlists().list(
            part="snippet,contentDetails",
            channelId=channel_id,
            maxResults=50,
            pageToken=page_token,
        ).execute()

        for item in resp.get("items", []):
            snippet = item.get("snippet", {})
            content = item.get("contentDetails", {})
            playlists.append(
                {
                    "id": str(item.get("id", "")),
                    "title": str(snippet.get("title", "")),
                    "item_count": str(content.get("itemCount", "")),
                }
            )

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return playlists


def fetch_playlist_items(youtube, playlist_id: str, playlist_title: str) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    page_token = None
    while True:
        resp = youtube.playlistItems().list(
            part="snippet,contentDetails",
            playlistId=playlist_id,
            maxResults=50,
            pageToken=page_token,
        ).execute()

        for entry in resp.get("items", []):
            snippet = entry.get("snippet", {})
            content = entry.get("contentDetails", {})
            video_id = str(content.get("videoId") or snippet.get("resourceId", {}).get("videoId", ""))
            if not video_id:
                continue

            thumbnails = snippet.get("thumbnails", {})
            thumb_url = (
                thumbnails.get("high", {}).get("url")
                or thumbnails.get("medium", {}).get("url")
                or thumbnails.get("default", {}).get("url")
                or ""
            )

            items.append(
                {
                    "video_id": video_id,
                    "title": str(snippet.get("title", "")),
                    "description": str(snippet.get("description", "")),
                    "published_at": str(snippet.get("publishedAt", "")),
                    "thumbnail_url": thumb_url,
                    "playlist_id": playlist_id,
                    "playlist_title": playlist_title,
                }
            )

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return items


def fetch_video_details(youtube, video_ids: Iterable[str]) -> Dict[str, Dict[str, str]]:
    details: Dict[str, Dict[str, str]] = {}
    for chunk in _chunk([vid for vid in video_ids if vid], 50):
        resp = youtube.videos().list(
            part="snippet,status,contentDetails",
            id=",".join(chunk),
            maxResults=50,
        ).execute()
        for item in resp.get("items", []):
            vid = str(item.get("id", ""))
            snippet = item.get("snippet", {})
            status = item.get("status", {})
            details[vid] = {
                "tags": ",".join(snippet.get("tags", [])) if snippet.get("tags") else "",
                "category_id": str(snippet.get("categoryId", "")),
                "privacy_status": str(status.get("privacyStatus", "")),
            }
    return details


def build_import_rows(items: List[Dict[str, str]], details: Dict[str, Dict[str, str]]) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for item in items:
        video_id = item.get("video_id", "")
        detail = details.get(video_id, {})
        row = {col: "" for col in REQUIRED_COLUMNS}
        row["video_id"] = video_id
        row["youtube_url"] = f"https://youtube.com/watch?v={video_id}" if video_id else ""
        row["title"] = item.get("title", "")
        row["description"] = item.get("description", "")
        row["tags"] = detail.get("tags", "")
        row["category_id"] = detail.get("category_id", "")
        row["privacy_status"] = detail.get("privacy_status", "")
        row["playlist"] = item.get("playlist_id", "")
        row["status"] = "IMPORTED"
        row["uploaded_at"] = ""
        row["error_message"] = ""

        rows.append(
            {
                "row": row,
                "thumbnail_url": item.get("thumbnail_url", ""),
                "playlist_title": item.get("playlist_title", ""),
                "playlist_id": item.get("playlist_id", ""),
                "video_id": video_id,
            }
        )
    return rows


def download_thumbnail(thumbnail_url: str, target_path: str) -> Optional[str]:
    if not thumbnail_url:
        return None
    try:
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with urlopen(thumbnail_url, timeout=10) as resp:
            data = resp.read()
        with open(target_path, "wb") as f:
            f.write(data)
        return normalize_path(target_path)
    except Exception as err:
        logging.warning("Thumbnail download failed: %s", err)
        return None


def download_video(
    video_url: str,
    output_dir: str,
    quality: str,
    use_aria2c: bool = False,
) -> Optional[str]:
    try:
        from yt_dlp import YoutubeDL
    except Exception as err:
        raise RuntimeError("yt-dlp is not installed. Please install dependencies.") from err

    os.makedirs(output_dir, exist_ok=True)

    format_map = {
        "best": "bestvideo+bestaudio/best",
        "1080p": "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
        "720p": "bestvideo[height<=720]+bestaudio/best[height<=720]",
    }
    fmt = format_map.get(quality, format_map["best"])

    ydl_opts = {
        "format": fmt,
        "outtmpl": os.path.join(output_dir, "%(title).80s [%(id)s].%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "continuedl": True,
        "retries": 10,
        "fragment_retries": 10,
        "concurrent_fragment_downloads": 4,
        "noprogress": True,
    }

    if use_aria2c:
        if shutil.which("aria2c"):
            ydl_opts["external_downloader"] = "aria2c"
            ydl_opts["external_downloader_args"] = [
                "-x",
                "8",
                "-s",
                "8",
                "-k",
                "1M",
            ]
        else:
            logging.warning("aria2c not found; falling back to native downloader.")

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video_url, download=True)
        filename = ydl.prepare_filename(info)
        return normalize_path(filename)


def import_playlists(
    youtube,
    playlist_items_by_id: Dict[str, str],
    excel_path: str,
    download_videos: bool = False,
    download_thumbnails: bool = False,
    base_download_dir: str = "",
    quality: str = "best",
    use_aria2c: bool = False,
    progress_callback=None,
    stop_event=None,
) -> int:
    all_rows: List[Dict[str, object]] = []
    playlist_ids = list(playlist_items_by_id.keys())

    for index, playlist_id in enumerate(playlist_ids, start=1):
        if stop_event and stop_event.is_set():
            raise InterruptedError("Import canceled by user.")

        title = playlist_items_by_id.get(playlist_id, playlist_id)
        if progress_callback:
            progress_callback("playlist", index, len(playlist_ids), title)

        items = fetch_playlist_items(youtube, playlist_id, title)
        details = fetch_video_details(youtube, [item["video_id"] for item in items])
        rows = build_import_rows(items, details)

        if download_videos or download_thumbnails:
            playlist_dir = os.path.join(base_download_dir, sanitize_filename(title or playlist_id))
            videos_dir = os.path.join(playlist_dir, "videos")
            thumbs_dir = os.path.join(playlist_dir, "thumbnails")

            total_rows = len(rows)
            for idx, item in enumerate(rows, start=1):
                if stop_event and stop_event.is_set():
                    raise InterruptedError("Import canceled by user.")

                row = item["row"]
                if progress_callback:
                    progress_callback("download", idx, total_rows, row.get("title", ""))

                if download_videos:
                    try:
                        video_url = row.get("youtube_url", "")
                        saved = download_video(
                            video_url=video_url,
                            output_dir=videos_dir,
                            quality=quality,
                            use_aria2c=use_aria2c,
                        )
                        if saved:
                            row["video_path"] = saved
                            row["status"] = "DOWNLOADED"
                    except Exception as err:
                        row["status"] = "FAILED"
                        row["error_message"] = str(err)

                if download_thumbnails:
                    thumb_url = item.get("thumbnail_url", "")
                    if thumb_url:
                        name = f"{item.get('video_id', '')}.jpg"
                        thumb_path = os.path.join(thumbs_dir, name)
                        saved_thumb = download_thumbnail(thumb_url, thumb_path)
                        if saved_thumb:
                            row["thumbnail_path"] = saved_thumb

        all_rows.extend(rows)

    export_rows(all_rows, excel_path)
    return len(all_rows)


def export_rows(rows: List[Dict[str, object]], excel_path: str) -> None:
    os.makedirs(os.path.dirname(excel_path), exist_ok=True)
    data = [item["row"] for item in rows]
    df = pd.DataFrame(data, columns=REQUIRED_COLUMNS)
    df.to_excel(excel_path, index=False)
