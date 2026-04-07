# YouTube Upload Manager

A Python desktop tool to automate YouTube video uploads using the YouTube Data API.

## Features

- Upload videos automatically from an Excel queue
- GUI selectors for Excel file, videos folder, and thumbnails folder
- Optional thumbnail upload
- Optional playlist assignment (playlist ID)
- Import playlists from any channel and export to Excel (optional downloads)
- Pause / Resume / Stop upload process
- Multiple YouTube account support
- GUI interface with preview and upload stats

## Project Structure

```text
YouTubeUploadManager
├── auth
│   ├── credentials.json
│   └── accounts/
├── cache
├── config
├─ core
├── data
├── gui
├── logs
├── storage
│   ├── videos
│   └── thumbnails
├── main.py
└── requirements.txt
```

## Running

1. Install dependencies: `pip install -r requirements.txt`
2. Add your OAuth client file at `auth/credentials.json`
3. Start the app: `python main.py`
