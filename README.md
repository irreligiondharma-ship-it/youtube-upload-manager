# YouTube Upload Manager

A Python desktop tool to automate YouTube video uploads using the YouTube Data API.

## Features

- Upload videos automatically from an Excel queue
- GUI selectors for Excel file, videos folder, and thumbnails folder
- Optional thumbnail upload
- Optional playlist assignment (playlist ID)
- Delay between uploads with skip controls
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
├── requirements.txt
└── run_app.bat