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
            raise ValueError("Thumbnail must be a JPG or PNG image.")
        if os.path.getsize(absolute_path) <= 0:
            raise ValueError("Thumbnail file is empty or corrupted.")
        return absolute_path

    # ===============================
    # Title
    # ===============================
    def validate_title(self, title):
        if not title or str(title).strip() == "":
            raise ValueError("Title cannot be empty.")

        if len(str(title)) > 100:
            raise ValueError("Title exceeds 100 characters.")

        return str(title).strip()

    # ===============================
    # Description
    # ===============================
    def validate_description(self, description):
        if not description:
            return ""
        return str(description)

    # ===============================
    # Tags
    # ===============================
    def validate_tags(self, tags):
        if not tags:
            return []

        if isinstance(tags, str):
            return [t.strip() for t in tags.split(",") if t.strip()]

        return []

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
            return dt_utc.isoformat().replace("+00:00", "Z")
        except ValueError:
            raise ValueError("Invalid schedule_time format. Use YYYY-MM-DD HH:MM")
