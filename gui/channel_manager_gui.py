import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import pandas as pd

from core.channel_manager import fetch_channel_videos


class ChannelManagerGUI:
    def __init__(self, root, youtube_client, account_name=""):
        self.root = root
        self.youtube = youtube_client
        self.account_name = account_name or "Unknown"
        self.videos = []
        self._busy = False

        self.dialog = tk.Toplevel(root)
        self.dialog.title("Channel Manager")
        self.dialog.transient(root)
        self.dialog.grab_set()
        self.dialog.geometry("720x500")
        self.dialog.resizable(True, True)

        header = ttk.Frame(self.dialog, padding=8)
        header.pack(fill="x")
        ttk.Label(header, text=f"Account: {self.account_name}").pack(side="left")

        controls = ttk.Frame(self.dialog, padding=8)
        controls.pack(fill="x")
        self.fetch_button = ttk.Button(controls, text="Fetch Channel Videos", command=self.fetch_videos)
        self.fetch_button.pack(side="left")
        self.export_button = ttk.Button(controls, text="Export to Excel", command=self.export_excel, state="disabled")
        self.export_button.pack(side="left", padx=6)

        self.status_label = ttk.Label(self.dialog, text="Status: Idle")
        self.status_label.pack(anchor="w", padx=8)

        self.listbox = tk.Listbox(self.dialog)
        self.listbox.pack(fill="both", expand=True, padx=8, pady=8)

        bottom = ttk.Frame(self.dialog, padding=8)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="Close", command=self.dialog.destroy).pack(side="right")

    def set_status(self, text):
        self.status_label.config(text=text)

    def fetch_videos(self):
        if self._busy:
            return
        self._busy = True
        self.fetch_button.config(state="disabled")
        self.export_button.config(state="disabled")
        self.listbox.delete(0, tk.END)
        self.set_status("Status: Fetching videos...")

        def run():
            try:
                videos = fetch_channel_videos(self.youtube, progress_callback=self.on_progress)
                self.videos = videos
                self.root.after(0, self.on_fetch_done)
            except Exception as err:
                self.root.after(0, lambda: self.on_fetch_error(err))

        threading.Thread(target=run, daemon=True).start()

    def on_progress(self, count):
        self.root.after(0, lambda: self.set_status(f"Status: Fetched {count} videos..."))

    def on_fetch_done(self):
        for item in self.videos:
            title = item.get("title", "")
            vid = item.get("video_id", "")
            self.listbox.insert(tk.END, f"{title} ({vid})")
        self.set_status(f"Status: Done. Total {len(self.videos)} videos.")
        self.fetch_button.config(state="normal")
        self.export_button.config(state="normal" if self.videos else "disabled")
        self._busy = False

    def on_fetch_error(self, err):
        self.set_status("Status: Error")
        self.fetch_button.config(state="normal")
        self.export_button.config(state="disabled")
        self._busy = False
        messagebox.showerror("Error", str(err), parent=self.dialog)

    def export_excel(self):
        if not self.videos:
            messagebox.showinfo("No Data", "No videos to export.", parent=self.dialog)
            return
        path = filedialog.asksaveasfilename(
            title="Save Channel Videos Excel",
            defaultextension=".xlsx",
            filetypes=[("Excel Files", "*.xlsx"), ("All Files", "*.*")],
        )
        if not path:
            return
        df = pd.DataFrame(self.videos)
        df.to_excel(path, index=False)
        messagebox.showinfo("Exported", f"Saved {len(self.videos)} videos to Excel.", parent=self.dialog)
