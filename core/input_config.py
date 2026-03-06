import json
import os

from config.constants import EXCEL_FILE, INPUT_SOURCES_FILE, THUMBNAILS_DIR, VIDEOS_DIR


def load_input_sources():
    defaults = {
        "excel_file": EXCEL_FILE,
        "videos_dir": VIDEOS_DIR,
        "thumbnails_dir": THUMBNAILS_DIR,
        "last_account": "",
    }

    try:
        with open(INPUT_SOURCES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return defaults

    merged = defaults.copy()
    for key in defaults:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            merged[key] = value.strip()

    return merged


def save_input_sources(excel_file, videos_dir, thumbnails_dir, last_account=""):
    os.makedirs(os.path.dirname(INPUT_SOURCES_FILE), exist_ok=True)
    payload = {
        "excel_file": excel_file,
        "videos_dir": videos_dir,
        "thumbnails_dir": thumbnails_dir,
        "last_account": last_account,
    }
    with open(INPUT_SOURCES_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def save_last_account(account_name):
    current = load_input_sources()
    save_input_sources(
        excel_file=current["excel_file"],
        videos_dir=current["videos_dir"],
        thumbnails_dir=current["thumbnails_dir"],
        last_account=account_name or "",
    )