import os
import tkinter as tk
from core.logger import setup_logger
from gui.gui import YouTubeUploadGUI


def create_directories():
    folders = [
        "data",
        "auth",
        "auth/accounts",
        "storage",
        "storage/videos",
        "storage/thumbnails",
        "logs",
        "cache"
    ]
    for folder in folders:
        os.makedirs(folder, exist_ok=True)


def main():
    create_directories()
    setup_logger()

    root = tk.Tk()
    app = YouTubeUploadGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()