import os

APP_NAME = "YouTube Upload Manager"
WINDOW_WIDTH = 900
WINDOW_HEIGHT = 650

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = os.path.join(BASE_DIR, "data")
AUTH_DIR = os.path.join(BASE_DIR, "auth")
ACCOUNTS_DIR = os.path.join(AUTH_DIR, "accounts")
STORAGE_DIR = os.path.join(BASE_DIR, "storage")
VIDEOS_DIR = os.path.join(STORAGE_DIR, "videos")
THUMBNAILS_DIR = os.path.join(STORAGE_DIR, "thumbnails")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
CACHE_DIR = os.path.join(BASE_DIR, "cache")

EXCEL_FILE = os.path.join(DATA_DIR, "upload_queue.xlsx")
APP_STATE_FILE = os.path.join(DATA_DIR, "app_state.json")
INPUT_SOURCES_FILE = os.path.join(DATA_DIR, "input_sources.json")
CREDENTIALS_FILE = os.path.join(AUTH_DIR, "credentials.json")

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly"
]