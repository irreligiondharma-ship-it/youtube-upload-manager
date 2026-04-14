import os
from datetime import datetime, timezone
from config.constants import BASE_DIR, THUMBNAILS_DIR, VIDEOS_DIR
from core.path_utils import first_existing_path
from config.settings import DEFAULT_PRIVACY


ALLOWED_PRIVACY = ["public", "private", "unlisted"]


class Validator:

    def __init__(self, videos_dir=None, thumbnails_dir=None):
        self.videos_dir = videos_dir or VIDEOS_DIR
        self.thumbnails_dir = thumbnails_dir or THUMBNAILS_DIR

    # ===============================
    # SMART PATH RESOLVER
    # ===============================
    def resolve_path(self, path, default_folder=None):
        if not path or str(path).strip() == "":
            return None

        path = str(path).strip()

        candidates = []
        if os.path.isabs(path):
            candidates.append(path)
        else:
            if default_folder:
                candidates.append(os.path.join(default_folder, path))
            candidates.append(os.path.join(BASE_DIR, path))

        return first_existing_path(candidates)

    # ===============================
    # Video Validation
    # ===============================
    def validate_video(self, video_path):
        absolute_path = self.resolve_path(video_path, self.videos_dir)

        if not absolute_path:
            raise FileNotFoundError(f"Video not found: {video_path}")

        if os.path.getsize(absolute_path) <= 0:
            raise ValueError("Video file is empty or corrupted.")

        return absolute_path

    # ===============================
    # Thumbnail Validation
    # ===============================
    def validate_thumbnail(self, thumbnail_path):
        absolute_path = self.resolve_path(thumbnail_path, self.thumbnails_dir)

        if not absolute_path:
            return None

        ext = os.path.splitext(absolute_path)[1].lower()
        if ext not in {".jpg", ".jpeg", ".png"}:
            # Basic check, allow common formats
            pass
            
        file_size = os.path.getsize(absolute_path)
        if file_size <= 0:
            raise ValueError("Thumbnail file is empty or corrupted.")
        
        # YouTube Limit: 2MB
        if file_size > 2 * 1024 * 1024:
            raise ValueError(f"Thumbnail too large ({file_size / 1024 / 1024:.2f}MB). Max 2MB allowed.")
            
        return absolute_path

    # ===============================
    # Title
    # ===============================
    def validate_title(self, title):
        title_str = str(title or "").strip()
        if not title_str:
            raise ValueError("Title cannot be empty.")

        if len(title_str) > 100:
            raise ValueError(f"Title too long ({len(title_str)} characters). Max 100 allowed.")

        return title_str

    # ===============================
    # Description
    # ===============================
    def validate_description(self, description):
        desc_str = str(description or "").strip()
        # YouTube Limit: 5000 characters
        if len(desc_str) > 5000:
            raise ValueError(f"Description too long ({len(desc_str)} characters). Max 5000 allowed.")
        return desc_str

    # ===============================
    # Tags
    # ===============================
    def validate_tags(self, tags):
        if not tags:
            return []

        tag_list = []
        if isinstance(tags, str):
            tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        elif isinstance(tags, (list, tuple)):
            tag_list = [str(t).strip() for t in tags if str(t).strip()]

        # YouTube Limit: Total 500 characters across all tags
        total_len = sum(len(tag) for tag in tag_list) + (len(tag_list) - 1 if tag_list else 0)
        if total_len > 500:
             raise ValueError(f"Total tags length ({total_len}) exceeds YouTube's 500-character limit.")

        return tag_list

    # ===============================
    # Privacy
    # ===============================
    def validate_privacy(self, privacy_status):
        if not privacy_status or str(privacy_status).strip() == "":
            return DEFAULT_PRIVACY

        privacy_status = str(privacy_status).lower().strip()

        if privacy_status not in ALLOWED_PRIVACY:
            raise ValueError("Invalid privacy status.")

        return privacy_status

    # ===============================
    # Schedule
    # ===============================
    def validate_schedule(self, schedule_time):
        if not schedule_time or str(schedule_time).strip() == "":
            return None

        try:
            dt = datetime.strptime(str(schedule_time), "%Y-%m-%d %H:%M")
            local_tz = datetime.now().astimezone().tzinfo
            dt_local = dt.replace(tzinfo=local_tz)
            dt_utc = dt_local.astimezone(timezone.utc)
            if dt_utc <= datetime.now(timezone.utc):
                raise ValueError("schedule_time must be in the future.")
            return dt_utc.isoformat().replace("+00:00", "Z")
        except ValueError:
            raise ValueError("Invalid schedule_time format. Use YYYY-MM-DD HH:MM")
