import os
import logging
from datetime import datetime, timedelta
from config.constants import LOGS_DIR
from config.settings import LOG_LEVEL, LOG_RETENTION_DAYS


def _cleanup_old_logs():
    if not isinstance(LOG_RETENTION_DAYS, int) or LOG_RETENTION_DAYS <= 0:
        return

    cutoff = datetime.now() - timedelta(days=LOG_RETENTION_DAYS)
    try:
        entries = os.listdir(LOGS_DIR)
    except OSError:
        return

    for name in entries:
        if not name.lower().endswith(".log"):
            continue
        path = os.path.join(LOGS_DIR, name)
        file_time = None

        # Try to parse date prefix: YYYY-MM-DD_app.log
        if len(name) >= 10:
            try:
                file_time = datetime.strptime(name[:10], "%Y-%m-%d")
            except ValueError:
                file_time = None

        if file_time is None:
            try:
                file_time = datetime.fromtimestamp(os.path.getmtime(path))
            except OSError:
                continue

        if file_time < cutoff:
            try:
                os.remove(path)
                logging.info("Deleted old log file: %s", name)
            except OSError as err:
                logging.warning("Failed to delete old log %s: %s", name, err)

def setup_logger():
    os.makedirs(LOGS_DIR, exist_ok=True)

    date_str = datetime.now().strftime("%Y-%m-%d")
    app_log_file = os.path.join(LOGS_DIR, f"{date_str}_app.log")

    level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(app_log_file, encoding="utf-8"),
            logging.StreamHandler()
        ]
    )

    _cleanup_old_logs()

    logging.info("Logger initialized.")
