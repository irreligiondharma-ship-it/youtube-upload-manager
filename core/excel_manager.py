import os
import logging
import pandas as pd
from datetime import datetime
from config.constants import EXCEL_FILE
from core.path_utils import normalize_path


REQUIRED_COLUMNS = [
    "video_path",
    "thumbnail_path",
    "title",
    "description",
    "tags",
    "playlist",
    "category_id",
    "privacy_status",
    "schedule_time",
    "status",
    "video_id",
    "youtube_url",
    "uploaded_at",
    "error_message"
]


class ExcelManager:

    def __init__(self, excel_file=None, videos_dir=None):
        self.excel_file = excel_file or EXCEL_FILE
        self.videos_dir = videos_dir
        self.df = None
        self._last_mtime = None
        self._pending_save = False
        self.load_excel(force=True)

    # ===============================
    # Load or Create Excel
    # ===============================
    def load_excel(self, force=False):
        parent_dir = os.path.dirname(self.excel_file)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

        if self._pending_save:
            return False

        if (not force) and (self.df is not None) and os.path.exists(self.excel_file):
            current_mtime = os.path.getmtime(self.excel_file)
            if self._last_mtime is not None and current_mtime == self._last_mtime:
                return False

        if not os.path.exists(self.excel_file):
            logging.info("Excel file not found. Creating new one.")
            self.df = pd.DataFrame(columns=REQUIRED_COLUMNS)
            self.save()
        else:
            try:
                ext = os.path.splitext(self.excel_file)[1].lower()
                engine = None
                if ext in (".xlsx", ".xlsm", ".xltx", ".xltm"):
                    engine = "openpyxl"
                elif ext == ".xls":
                    engine = "xlrd"

                if engine:
                    self.df = pd.read_excel(self.excel_file, dtype=str, engine=engine)
                else:
                    # Try openpyxl as a sensible default
                    self.df = pd.read_excel(self.excel_file, dtype=str, engine="openpyxl")
            except (PermissionError, OSError) as err:
                logging.warning("Excel read skipped due to transient file access issue: %s", err)
                return False
            except (ValueError, ImportError) as err:
                logging.warning("Excel read failed: %s", err)
                if self.df is None:
                    self.df = pd.DataFrame(columns=REQUIRED_COLUMNS)
                return False
            self._ensure_columns()

        # Replace NaN with empty string (VERY IMPORTANT)
        self.df.fillna("", inplace=True)

        # Auto-default blank status rows to PENDING for executable queue entries
        if "status" in self.df.columns and "video_path" in self.df.columns:
            mask = (self.df["video_path"].astype(str).str.strip() != "") & (
                self.df["status"].astype(str).str.strip() == ""
            )
            if mask.any():
                self.df.loc[mask, "status"] = "PENDING"
                self.save()

        if os.path.exists(self.excel_file):
            self._last_mtime = os.path.getmtime(self.excel_file)

        return True

    # ===============================
    # Ensure Required Columns
    # ===============================
    def _ensure_columns(self):
        has_changes = False
        for col in REQUIRED_COLUMNS:
            if col not in self.df.columns:
                self.df[col] = ""
                has_changes = True
        if has_changes:
            self.save()

    # ===============================
    # Save Excel
    # ===============================
    def save(self):
        try:
            self.df.to_excel(self.excel_file, index=False)
            if os.path.exists(self.excel_file):
                self._last_mtime = os.path.getmtime(self.excel_file)
            self._pending_save = False
        except (PermissionError, OSError) as err:
            self._pending_save = True
            logging.warning("Excel save skipped due to file lock or access issue: %s", err)

    def flush_pending_save(self):
        if not self._pending_save:
            return False
        self.save()
        return not self._pending_save

    def reload(self):
        self.load_excel(force=True)

    def reload_if_changed(self):
        return self.load_excel(force=False)

    # ===============================
    # Get Pending Rows
    # ===============================
    def get_pending_rows(self):
        status_series = self.df["status"].astype(str).str.strip().str.upper()
        return self.df[status_series == "PENDING"]

    def get_next_pending_index(self):
        pending = self.get_pending_rows()
        if pending.empty:
            return None
        return pending.index[0]

    # ===============================
    # Status Updates
    # ===============================
    def mark_uploading(self, index):
        self.df.at[index, "status"] = "UPLOADING"
        self.save()

    def mark_uploaded(self, index, video_id):
        youtube_url = f"https://youtube.com/watch?v={video_id}"

        self.df.at[index, "status"] = "UPLOADED"
        self.df.at[index, "video_id"] = str(video_id)
        self.df.at[index, "youtube_url"] = youtube_url
        self.df.at[index, "uploaded_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.df.at[index, "error_message"] = ""
        self.save()

    def mark_uploaded_with_warning(self, index, video_id, warning_message):
        youtube_url = f"https://youtube.com/watch?v={video_id}"

        self.df.at[index, "status"] = "UPLOADED_WITH_WARNINGS"
        self.df.at[index, "video_id"] = str(video_id)
        self.df.at[index, "youtube_url"] = youtube_url
        self.df.at[index, "uploaded_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.df.at[index, "error_message"] = str(warning_message)
        self.save()

    def mark_failed(self, index, error_message):
        self.df.at[index, "status"] = "FAILED"
        self.df.at[index, "error_message"] = str(error_message)
        self.save()

    def mark_skipped(self, index, reason="Duplicate"):
        self.df.at[index, "status"] = "SKIPPED"
        self.df.at[index, "error_message"] = str(reason)
        self.save()

    def reset_uploading_rows(self):
        status_series = self.df["status"].astype(str).str.strip().str.upper()
        uploading_rows = self.df[status_series == "UPLOADING"]
        if not uploading_rows.empty:
            self.df.loc[status_series == "UPLOADING", "status"] = "PENDING"
            self.save()
            logging.info("Reset stuck UPLOADING rows to PENDING.")


    def _normalize_video_path(self, video_path):
        if not video_path:
            return ""

        raw = str(video_path).strip()
        if not raw:
            return ""

        queue_base_dir = os.path.dirname(os.path.abspath(self.excel_file))
        base_dir = self.videos_dir or queue_base_dir
        candidate = raw if os.path.isabs(raw) else os.path.join(base_dir, raw)
        return normalize_path(candidate)

    # ===============================
    # Duplicate Check
    # ===============================
    def is_duplicate(self, video_path):
        target = self._normalize_video_path(video_path)
        if not target:
            return False

        status_series = self.df["status"].astype(str).str.strip().str.upper()
        uploaded = self.df[status_series.isin(["UPLOADED", "UPLOADED_WITH_WARNINGS"])]
        for existing_path in uploaded["video_path"].tolist():
            if self._normalize_video_path(existing_path) == target:
                return True
        return False

    # ===============================
    # Stats
    # ===============================
    def get_stats(self):
        total = len(self.df)
        status_series = self.df["status"].astype(str).str.strip().str.upper()
        uploaded = len(self.df[status_series.isin(["UPLOADED", "UPLOADED_WITH_WARNINGS"])])
        failed = len(self.df[status_series == "FAILED"])
        pending = len(self.df[status_series == "PENDING"])
        skipped = len(self.df[status_series == "SKIPPED"])

        return {
            "total": total,
            "uploaded": uploaded,
            "failed": failed,
            "pending": pending,
            "skipped": skipped
        }
