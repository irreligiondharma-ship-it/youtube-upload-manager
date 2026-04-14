import logging
import os
import re
import shutil
import time
from typing import Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import urlparse
from urllib.request import urlopen

import pandas as pd

from core.excel_manager import REQUIRED_COLUMNS
from core.path_utils import normalize_path


_CHANNEL_ID_RE = re.compile(r"(UC[a-zA-Z0-9_-]{20,})")
_HANDLE_RE = re.compile(r"@([A-Za-z0-9_.-]+)")
_INVALID_PATH_CHARS = re.compile(r'[<>:"/\\\\|?*]+')
_VIDEO_ID_RE = re.compile(r"(?:v=|youtu\.be/|shorts/|embed/)([A-Za-z0-9_-]{11})")


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


def extract_video_id(video_input: str) -> str:
    raw = str(video_input or "").strip()
    if not raw:
        return ""

    match = _VIDEO_ID_RE.search(raw)
    if match:
        return match.group(1)

    if re.fullmatch(r"[A-Za-z0-9_-]{11}", raw):
        return raw

    return ""


def find_existing_video_file(output_dir: str, video_id: str) -> Optional[str]:
    if not output_dir or not video_id:
        return None
    if not os.path.isdir(output_dir):
        return None

    allowed_exts = {
        ".mp4",
        ".mkv",
        ".webm",
        ".mov",
        ".m4v",
        ".avi",
        ".flv",
    }
    temp_suffixes = (
        ".part",
        ".ytdl",
        ".aria2",
        ".frag",
        ".frag.urls",
        ".part.frag",
        ".part.frag.urls",
    )

    needle = f"[{video_id}]"
    for name in os.listdir(output_dir):
        if needle not in name:
            continue
        lowered = name.lower()
        if lowered.endswith(temp_suffixes):
            continue
        path = os.path.join(output_dir, name)
        try:
            _, ext = os.path.splitext(name)
            if ext.lower() not in allowed_exts:
                continue
            if os.path.getsize(path) > 0:
                return normalize_path(path)
        except OSError:
            continue
    return None


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


def fetch_single_video_item(youtube, video_id: str) -> Tuple[Dict[str, str], Dict[str, str]]:
    resp = youtube.videos().list(part="snippet,status", id=video_id).execute()
    items = resp.get("items", [])
    if not items:
        raise ValueError("Video not found or not accessible.")

    item = items[0]
    snippet = item.get("snippet", {})
    status = item.get("status", {})
    thumbnails = snippet.get("thumbnails", {})
    thumb_url = (
        thumbnails.get("high", {}).get("url")
        or thumbnails.get("medium", {}).get("url")
        or thumbnails.get("default", {}).get("url")
        or ""
    )

    base_item = {
        "video_id": video_id,
        "title": str(snippet.get("title", "")),
        "description": str(snippet.get("description", "")),
        "published_at": str(snippet.get("publishedAt", "")),
        "thumbnail_url": thumb_url,
        "playlist_id": "",
        "playlist_title": "",
    }

    detail = {
        "tags": ",".join(snippet.get("tags", [])) if snippet.get("tags") else "",
        "category_id": str(snippet.get("categoryId", "")),
        "privacy_status": str(status.get("privacyStatus", "")),
    }

    return base_item, detail


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
    cookies_from_browser: Optional[str] = None,
    cookie_file: Optional[str] = None,
    progress_hook=None,
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

    def _build_ydl_opts(enable_aria2c: bool):
        ydl_opts = {
            "format": fmt,
            "outtmpl": os.path.join(output_dir, "%(title).80s [%(id)s].%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "continuedl": True,
            "retries": 3,
            "fragment_retries": 3,
            "concurrent_fragment_downloads": 4,
            "noprogress": True,
            "sleep_interval": 5, # Wait 5 seconds between downloads
            "max_sleep_interval": 10,
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }

        if progress_hook:
            def _hook(status):
                if not progress_hook:
                    return
                if status.get("status") == "downloading":
                    total = status.get("total_bytes") or status.get("total_bytes_estimate")
                    downloaded = status.get("downloaded_bytes", 0)
                    percent = None
                    if total:
                        try:
                            percent = int((downloaded / total) * 100)
                        except ZeroDivisionError:
                            percent = None
                    progress_hook(percent)
                elif status.get("status") == "finished":
                    progress_hook(100)

            ydl_opts["progress_hooks"] = [_hook]

        if cookie_file:
            ydl_opts["cookiefile"] = cookie_file
        elif cookies_from_browser:
            ydl_opts["cookiesfrombrowser"] = (cookies_from_browser,)

        if enable_aria2c:
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
        return ydl_opts

    def _run_download(enable_aria2c: bool):
        ydl_opts = _build_ydl_opts(enable_aria2c)
        with YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(video_url, download=True)
                filename = ydl.prepare_filename(info)
                return normalize_path(filename)
            except Exception as e:
                # If it's a cookie lock error, wait and retry once more with native
                if "Could not copy Chrome cookie database" in str(e) or "cookie" in str(e).lower():
                    logging.warning("Cookie issue detected. Waiting 5 seconds and retrying with native downloader...")
                    time.sleep(5)
                    # For retry, we try WITHOUT aria2c to be safer
                    ydl_opts_retry = _build_ydl_opts(False)
                    with YoutubeDL(ydl_opts_retry) as ydl_retry:
                        info = ydl_retry.extract_info(video_url, download=True)
                        filename = ydl_retry.prepare_filename(info)
                        return normalize_path(filename)
                raise

    try:
        return _run_download(use_aria2c)
    except Exception as err:
        if use_aria2c:
            logging.warning("aria2c download failed; retrying with native downloader: %s", err)
            return _run_download(False)
        raise


def import_playlists(
    youtube,
    playlist_items_by_id: Dict[str, str],
    excel_path: str,
    download_videos: bool = False,
    download_thumbnails: bool = False,
    base_download_dir: str = "",
    quality: str = "best",
    use_aria2c: bool = False,
    cookies_from_browser: Optional[str] = None,
    cookie_file: Optional[str] = None,
    skip_existing: bool = True,
    video_filter_map: Optional[Dict[str, Set[str]]] = None,
    progress_callback=None,
    stop_event=None,
) -> Dict[str, int]:
    all_rows: List[Dict[str, object]] = []
    playlist_ids = list(playlist_items_by_id.keys())
    
    summary = {"total": 0, "downloaded": 0, "failed": 0, "skipped": 0}

    for index, playlist_id in enumerate(playlist_ids, start=1):
        if stop_event and stop_event.is_set():
            raise InterruptedError("Import canceled by user.")

        title = playlist_items_by_id.get(playlist_id, playlist_id)
        if progress_callback:
            progress_callback("playlist", index, len(playlist_ids), title)

        items = fetch_playlist_items(youtube, playlist_id, title)
        filter_ids = None
        if video_filter_map and playlist_id in video_filter_map:
            filter_ids = video_filter_map.get(playlist_id)
        if filter_ids:
            items = [item for item in items if item.get("video_id") in filter_ids]
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

                summary["total"] += 1
                row = item["row"]
                def _progress(percent):
                    if progress_callback:
                        progress_callback("download", idx, total_rows, row.get("title", ""), percent)

                if progress_callback:
                    progress_callback("download", idx, total_rows, row.get("title", ""), None)

                if download_videos:
                    try:
                        video_url = row.get("youtube_url", "")
                        if skip_existing:
                            existing = find_existing_video_file(videos_dir, item.get("video_id", ""))
                        else:
                            existing = None

                        if existing:
                            row["video_path"] = existing
                            row["status"] = "SKIPPED_ALREADY_DOWNLOADED"
                            row["error_message"] = "Already downloaded"
                            summary["skipped"] += 1
                            _progress(100)
                        else:
                            saved = download_video(
                                video_url=video_url,
                                output_dir=videos_dir,
                                quality=quality,
                                use_aria2c=use_aria2c,
                                cookies_from_browser=cookies_from_browser,
                                cookie_file=cookie_file,
                                progress_hook=_progress,
                            )
                            if saved:
                                row["video_path"] = saved
                                row["status"] = "DOWNLOADED"
                                summary["downloaded"] += 1
                    except Exception as err:
                        row["status"] = "FAILED"
                        row["error_message"] = str(err)
                        summary["failed"] += 1
                else:
                    # Metadata only import
                    summary["downloaded"] += 1

                if download_thumbnails:
                    thumb_url = item.get("thumbnail_url", "")
                    if thumb_url:
                        name = f"{item.get('video_id', '')}.jpg"
                        thumb_path = os.path.join(thumbs_dir, name)
                        saved_thumb = download_thumbnail(thumb_url, thumb_path)
                        if saved_thumb:
                            row["thumbnail_path"] = saved_thumb
        else:
            summary["total"] += len(rows)
            summary["downloaded"] += len(rows)

        all_rows.extend(rows)

    export_rows(all_rows, excel_path)
    return summary


def import_single_video(
    youtube,
    video_input: str,
    excel_path: str,
    download_videos: bool = True,
    download_thumbnails: bool = False,
    base_download_dir: str = "",
    quality: str = "best",
    use_aria2c: bool = False,
    cookies_from_browser: Optional[str] = None,
    cookie_file: Optional[str] = None,
    skip_existing: bool = True,
    progress_callback=None,
    stop_event=None,
) -> Dict[str, int]:
    video_id = extract_video_id(video_input)
    if not video_id:
        raise ValueError("Invalid video URL or ID.")

    if stop_event and stop_event.is_set():
        raise InterruptedError("Import canceled by user.")

    item, detail = fetch_single_video_item(youtube, video_id)
    rows = build_import_rows([item], {video_id: detail})

    summary = {"total": 1, "downloaded": 0, "failed": 0, "skipped": 0}
    row = rows[0]["row"]
    if progress_callback:
        progress_callback("download", 1, 1, row.get("title", ""), None)

    if download_videos or download_thumbnails:
        single_dir = os.path.join(base_download_dir, "single")
        videos_dir = os.path.join(single_dir, "videos")
        thumbs_dir = os.path.join(single_dir, "thumbnails")

        def _progress(percent):
            if progress_callback:
                progress_callback("download", 1, 1, row.get("title", ""), percent)

        if download_videos:
            try:
                if skip_existing:
                    existing = find_existing_video_file(videos_dir, video_id)
                else:
                    existing = None
                if existing:
                    row["video_path"] = existing
                    row["status"] = "SKIPPED_ALREADY_DOWNLOADED"
                    row["error_message"] = "Already downloaded"
                    summary["skipped"] = 1
                    _progress(100)
                else:
                    saved = download_video(
                        video_url=row.get("youtube_url", ""),
                        output_dir=videos_dir,
                        quality=quality,
                        use_aria2c=use_aria2c,
                        cookies_from_browser=cookies_from_browser,
                        cookie_file=cookie_file,
                        progress_hook=_progress,
                    )
                    if saved:
                        row["video_path"] = saved
                        row["status"] = "DOWNLOADED"
                        summary["downloaded"] = 1
            except Exception as err:
                row["status"] = "FAILED"
                row["error_message"] = str(err)
                summary["failed"] = 1
        else:
            summary["downloaded"] = 1

        if download_thumbnails:
            thumb_url = rows[0].get("thumbnail_url", "")
            if thumb_url:
                name = f"{video_id}.jpg"
                thumb_path = os.path.join(thumbs_dir, name)
                saved_thumb = download_thumbnail(thumb_url, thumb_path)
                if saved_thumb:
                    row["thumbnail_path"] = saved_thumb
    else:
        summary["downloaded"] = 1

    export_rows(rows, excel_path)
    return summary


def export_rows(rows: List[Dict[str, object]], excel_path: str) -> None:
    parent_dir = os.path.dirname(excel_path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)
    data = [item["row"] for item in rows]
    df = pd.DataFrame(data, columns=REQUIRED_COLUMNS)
    
    try:
        df.to_excel(excel_path, index=False)
        # If successful, remove any temp file
        temp_file = excel_path + ".tmp"
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except:
                pass
    except (PermissionError, OSError) as err:
        temp_file = excel_path + ".tmp"
        logging.warning("Excel file %s is locked. Saving to temporary backup: %s", excel_path, temp_file)
        try:
            df.to_excel(temp_file, index=False)
            logging.info("Import data safely backed up to %s", temp_file)
        except Exception as e:
            logging.error("CRITICAL: Failed to save even to temporary file: %s", e)
            raise err
