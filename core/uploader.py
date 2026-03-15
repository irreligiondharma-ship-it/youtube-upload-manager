import json
import logging
import os
from threading import Event

from config.constants import APP_STATE_FILE
from config.settings import AUTO_RESUME_ON_START, RETRY_LIMIT
from core.excel_manager import ExcelManager
from core.validator import Validator
from core.youtube_service import YouTubeService


class Uploader:
    def __init__(
        self,
        youtube_client,
        account_name=None,
        progress_callback=None,
        status_callback=None,
        excel_file=None,
        videos_dir=None,
        thumbnails_dir=None,
    ):
        self.youtube_service = YouTubeService(youtube_client)
        self.excel = ExcelManager(excel_file=excel_file, videos_dir=videos_dir)
        self.validator = Validator(videos_dir=videos_dir, thumbnails_dir=thumbnails_dir)

        self.account_name = account_name
        self.progress_callback = progress_callback
        self.status_callback = status_callback

        self.stop_event = Event()
        self.pause_event = Event()
        self.pause_event.set()

        self.state = {}
        self.load_state()

        self.excel.reset_uploading_rows()

    def save_state(self, current_index=None):
        state_file_dir = os.path.dirname(APP_STATE_FILE)
        if state_file_dir:
            os.makedirs(state_file_dir, exist_ok=True)
        active_excel_file = str(getattr(self.excel, "excel_file", "")).strip()

        state_data = {
            "current_index": int(current_index) if current_index is not None else None,
            "account_name": self.account_name,
            "excel_file": os.path.abspath(active_excel_file) if active_excel_file else "",
        }

        with open(APP_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state_data, f)

    def load_state(self):
        try:
            with open(APP_STATE_FILE, "r", encoding="utf-8") as f:
                self.state = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.state = {}

    def stop(self):
        self.stop_event.set()
        # Unblock if currently paused so thread can exit promptly
        self.pause_event.set()
        self._notify_status("state_change", state="stopping")

    def pause(self):
        self.pause_event.clear()
        self._notify_status("state_change", state="paused")

    def resume(self):
        self.pause_event.set()
        self._notify_status("state_change", state="running")

    def _get_resume_index(self):
        if not AUTO_RESUME_ON_START:
            return None

        state_account = str(self.state.get("account_name", "")).strip()
        if state_account and self.account_name and state_account != self.account_name:
            logging.info(
                "State account (%s) does not match current account (%s); ignoring resume index.",
                state_account,
                self.account_name,
            )
            return None

        state_excel = str(self.state.get("excel_file", "")).strip()
        active_excel_file = str(getattr(self.excel, "excel_file", "")).strip()
        if state_excel and active_excel_file and os.path.abspath(state_excel) != os.path.abspath(active_excel_file):
            logging.info(
                "State excel_file (%s) does not match active queue (%s); ignoring resume index.",
                state_excel,
                active_excel_file,
            )
            return None

        raw_index = self.state.get("current_index")
        if raw_index is None:
            return None

        try:
            resume_index = int(raw_index)
        except (TypeError, ValueError):
            logging.warning("Invalid resume index in state file: %s", raw_index)
            return None

        if resume_index not in self.excel.df.index:
            logging.warning("Resume index %s not found in queue; ignoring.", resume_index)
            return None

        status = str(self.excel.df.at[resume_index, "status"]).strip().upper()
        if status in {"UPLOADED", "FAILED", "SKIPPED"}:
            logging.info("Resume index %s already terminal state (%s); ignoring.", resume_index, status)
            return None

        return resume_index

    def _notify_progress(self, value):
        if not self.progress_callback:
            return
        try:
            self.progress_callback(value)
        except Exception as err:
            logging.warning("Progress callback failed: %s", err)

    def _notify_status(self, event, **payload):
        if not self.status_callback:
            return
        try:
            self.status_callback(event, payload)
        except Exception as err:
            logging.warning("Status callback failed: %s", err)

    def _classify_error(self, err):
        if isinstance(err, (FileNotFoundError, ValueError)):
            return "validation"
        if isinstance(err, PermissionError):
            return "filesystem"
        if isinstance(err, (TimeoutError, ConnectionError)):
            return "network"

        message = str(err).lower()
        if "quota" in message or "rate limit" in message:
            return "api_quota"
        if "auth" in message or "token" in message or "credential" in message:
            return "authentication"
        if "http" in message or "api" in message:
            return "api"

        return "runtime"

    def _log_upload_error(self, index, row, err):
        category = self._classify_error(err)
        logging.error(
            "Upload failed | category=%s | error_type=%s | index=%s | account=%s | title=%s | video_path=%s | error=%s",
            category,
            type(err).__name__,
            index,
            self.account_name,
            row.get("title", ""),
            row.get("video_path", ""),
            err,
        )

    def start(self):
        self._notify_status("state_change", state="running")
        resume_index = self._get_resume_index()
        if resume_index is not None:
            logging.info("Resuming from index: %s", resume_index)

        while not self.stop_event.is_set():
            self.pause_event.wait()

            if resume_index is not None:
                index = resume_index
                resume_index = None
            else:
                index = self.excel.get_next_pending_index()

            if index is None:
                logging.info("No more pending videos.")
                break

            row = self.excel.df.loc[index]
            self._notify_status(
                "item_start",
                index=int(index),
                title=str(row.get("title", "")).strip(),
                video_path=str(row.get("video_path", "")).strip(),
            )

            try:
                self.save_state(current_index=index)

                if self.excel.is_duplicate(row["video_path"]):
                    self.excel.mark_skipped(index, "Duplicate video")
                    continue

                self.excel.mark_uploading(index)

                video_path = self.validator.validate_video(row["video_path"])
                thumbnail_path = self.validator.validate_thumbnail(row["thumbnail_path"])
                title = self.validator.validate_title(row["title"])
                description = self.validator.validate_description(row["description"])
                tags = self.validator.validate_tags(row["tags"])
                privacy = self.validator.validate_privacy(row["privacy_status"])
                schedule = self.validator.validate_schedule(row["schedule_time"])
                playlist_id = str(row.get("playlist", "")).strip()
                category_id = str(row.get("category_id", "22")).strip() or "22"

                video_id = None
                attempt = 0

                while attempt <= RETRY_LIMIT:
                    try:
                        video_id = self.youtube_service.upload_video(
                            video_path=video_path,
                            title=title,
                            description=description,
                            tags=tags,
                            privacy_status=privacy,
                            category_id=category_id,
                            publish_at=schedule,
                            progress_callback=self._notify_progress,
                            pause_event=self.pause_event,
                            stop_event=self.stop_event,
                        )
                        break
                    except Exception as err:
                        attempt += 1
                        if attempt > RETRY_LIMIT:
                            raise err
                        logging.warning("Retrying upload...")

                if thumbnail_path:
                    self.youtube_service.upload_thumbnail(video_id, thumbnail_path)

                if playlist_id:
                    self.youtube_service.add_video_to_playlist(video_id, playlist_id)

                self.excel.mark_uploaded(index, video_id)
                self.save_state(current_index=None)
                self._notify_status(
                    "item_done",
                    index=int(index),
                    video_id=str(video_id),
                    title=str(row.get("title", "")).strip(),
                )

            except Exception as err:
                if isinstance(err, InterruptedError):
                    reason = "Stopped by user"
                    self.excel.mark_skipped(index, reason)
                    self.save_state(current_index=None)
                    self._notify_status(
                        "item_failed",
                        index=int(index),
                        error=reason,
                        title=str(row.get("title", "")).strip(),
                    )
                else:
                    self._log_upload_error(index=index, row=row, err=err)
                    self.excel.mark_failed(index, str(err))
                    self.save_state(current_index=None)
                    self._notify_status(
                        "item_failed",
                        index=int(index),
                        error=str(err),
                        title=str(row.get("title", "")).strip(),
                    )

        logging.info("Uploader stopped.")
        self._notify_status("state_change", state="stopped")
