from __future__ import annotations

from typing import Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import Resource, build
from googleapiclient.http import MediaFileUpload


class YouTubeService:
    def __init__(self, youtube_client_or_token_file):
        if isinstance(youtube_client_or_token_file, str):
            creds = Credentials.from_authorized_user_file(youtube_client_or_token_file)
            self.youtube: Resource = build("youtube", "v3", credentials=creds)
        else:
            # Already constructed youtube client from AccountManager
            self.youtube = youtube_client_or_token_file

    def upload_video(
        self,
        video_path: str,
        title: str,
        description: str,
        tags: list[str],
        privacy_status: str,
        category_id: str = "22",
        publish_at: Optional[str] = None,
        progress_callback=None,
        pause_event=None,
        stop_event=None,
    ) -> str:
        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": category_id,
            },
            "status": {
                "privacyStatus": privacy_status,
            },
        }

        if publish_at and privacy_status == "private":
            body["status"]["publishAt"] = publish_at

        media = MediaFileUpload(video_path, chunksize=1024 * 1024 * 2, resumable=True)

        request = self.youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )

        response = None
        while response is None:
            if stop_event and stop_event.is_set():
                raise InterruptedError("Upload stopped by user.")
            if pause_event:
                pause_event.wait()
            status, response = request.next_chunk()
            if status and progress_callback:
                percent = int(status.progress() * 100)
                progress_callback(percent)

        return response["id"]

    def upload_thumbnail(self, video_id: str, thumbnail_path: str) -> None:
        media = MediaFileUpload(thumbnail_path)
        self.youtube.thumbnails().set(videoId=video_id, media_body=media).execute()

    def add_video_to_playlist(self, video_id: str, playlist_id: str) -> None:
        if not playlist_id:
            return

        body = {
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {
                    "kind": "youtube#video",
                    "videoId": video_id,
                },
            }
        }

        self.youtube.playlistItems().insert(part="snippet", body=body).execute()
