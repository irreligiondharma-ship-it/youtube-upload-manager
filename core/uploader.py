import json
import logging
import os
import time
from threading import Event

from config.constants import APP_STATE_FILE
from config.settings import AUTO_RESUME_ON_START, DELAY_SECONDS, RETRY_LIMIT
from core.excel_manager import ExcelManager
from core.validator import Validator
from core.youtube_service import YouTubeService


class Uploader:
    def __init__(self, youtube_client, account_name=None, progress_callback=None, delay_callback=None, excel_file=None, videos_dir=None, thumbnails_dir=None):
        self.youtube_service = YouTubeService(youtube_client)
        self.excel = ExcelManager(excel_file=excel_file, videos_dir=videos_dir)
        self.validator = Validator(videos_dir=videos_dir, thumbnails_dir=thumbnails_dir)

        self.account_name = account_name
        self.progress_callback = progress_callback
        self.delay_callback = delay_callback

        self.stop_event = Event()
        self.pause_event = Event()
        self.pause_event.set()

        self.skip_current_delay = False
        self.skip_all_delay = False

        self.state = {}
        self.load_state()

        self.excel.reset_uploading_rows()
        self._restore_runtime_flags_from_state()

    def save_state(self, current_index=None):
        state_file_dir = os.path.dirname(APP_STATE_FILE)
        if state_file_dir:
            os.makedirs(state_file_dir, exist_ok=True)

        state_data = {
            "current_index": int(current_index) if current_index is not None else None,
            "account_name": self.account_name,
            "skip_all_delay": self.skip_all_delay,
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

    def pause(self):
        self.pause_event.clear()

    def resume(self):
        self.pause_event.set()

    def skip_current(self):
        self.skip_current_delay = True

    def skip_all(self):
        self.skip_all_delay = True

    def restore_delay(self):
        self.skip_all_delay = False

    def _restore_runtime_flags_from_state(self):
        if AUTO_RESUME_ON_START:
            self.skip_all_delay = bool(self.state.get("skip_all_delay", False))

    def _get_resume_index(self):
        if not AUTO_RESUME_ON_START:
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

    def _notify_delay(self, remaining=None, mode="running"):
        if not self.delay_callback:
            return
        try:
            self.delay_callback(remaining, mode)
        except Exception as err:
            logging.warning("Delay callback failed: %s", err)

    def _notify_progress(self, value):
        if not self.progress_callback:
            return
        try:
            self.progress_callback(value)
        except Exception as err:
            logging.warning("Progress callback failed: %s", err)

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

                self.run_delay()

            except Exception as err:
                self._log_upload_error(index=index, row=row, err=err)
                self.excel.mark_failed(index, str(err))
                self.save_state(current_index=None)

        logging.info("Uploader stopped.")

    def run_delay(self):
        if self.skip_all_delay:
            logging.info("Delay skipped (session mode).")
            self._notify_delay(None, "skipped_session")
            return

        if self.skip_current_delay:
            logging.info("Current delay skipped.")
            self.skip_current_delay = False
            self._notify_delay(None, "skipped_current")
            return

        logging.info("Starting delay: %s seconds", DELAY_SECONDS)

        for remaining in range(DELAY_SECONDS, 0, -1):
            if self.stop_event.is_set():
                break

            self.pause_event.wait()
            self._notify_delay(remaining, "running")

            if self.skip_current_delay:
                logging.info("Current delay skipped during countdown.")
                self.skip_current_delay = False
                self._notify_delay(None, "skipped_current")
                break

            time.sleep(1)

        logging.info("Delay finished.")
        self._notify_delay(0, "finished")