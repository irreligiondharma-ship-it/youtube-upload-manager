import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from config.constants import DATA_DIR, STORAGE_DIR
from core.channel_importer import (
    fetch_playlists,
    import_playlists,
    resolve_channel_id,
)


class ChannelImportGUI:
    def __init__(self, root, youtube_client):
        self.root = root
        self.youtube = youtube_client
        self.channel_id = ""
        self.playlists = []
        self.stop_event = threading.Event()

        self.dialog = tk.Toplevel(root)
        self.dialog.title("Channel Import / Download")
        self.dialog.transient(root)
        self.dialog.grab_set()
        self.dialog.geometry("900x640")
        self.dialog.resizable(True, True)

        header = ttk.Frame(self.dialog, padding=8)
        header.pack(fill="x")

        ttk.Label(header, text="Channel URL or ID").pack(side="left")
        self.channel_entry = ttk.Entry(header, width=60)
        self.channel_entry.pack(side="left", padx=6, fill="x", expand=True)
        ttk.Button(header, text="Fetch Playlists", command=self.fetch_playlists).pack(side="left")

        body = ttk.Frame(self.dialog, padding=8)
        body.pack(fill="both", expand=True)

        left = ttk.Frame(body)
        left.pack(side="left", fill="both", expand=True)

        ttk.Label(left, text="Playlists").pack(anchor="w")
        self.playlist_listbox = tk.Listbox(left, selectmode="extended")
        self.playlist_listbox.pack(fill="both", expand=True)

        playlist_buttons = ttk.Frame(left)
        playlist_buttons.pack(fill="x", pady=(6, 0))
        ttk.Button(playlist_buttons, text="Select All", command=self.select_all).pack(side="left")
        ttk.Button(playlist_buttons, text="Clear", command=self.clear_selection).pack(side="left", padx=6)

        right = ttk.Frame(body)
        right.pack(side="right", fill="both", expand=True, padx=(8, 0))

        options = ttk.LabelFrame(right, text="Options", padding=8)
        options.pack(fill="x")

        ttk.Label(options, text="Excel output").grid(row=0, column=0, sticky="w")
        self.excel_entry = ttk.Entry(options)
        self.excel_entry.grid(row=0, column=1, sticky="we", padx=6)
        ttk.Button(options, text="Browse", command=self.browse_excel).grid(row=0, column=2)
        self.excel_entry.insert(0, os.path.join(DATA_DIR, "channel_export.xlsx"))

        ttk.Label(options, text="Base download folder").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.base_folder_entry = ttk.Entry(options)
        self.base_folder_entry.grid(row=1, column=1, sticky="we", padx=6, pady=(6, 0))
        ttk.Button(options, text="Browse", command=self.browse_folder).grid(row=1, column=2, pady=(6, 0))
        self.base_folder_entry.insert(0, os.path.join(STORAGE_DIR, "downloads"))

        self.download_videos_var = tk.BooleanVar(value=False)
        self.download_thumbs_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(options, text="Download videos", variable=self.download_videos_var, command=self.toggle_downloads).grid(
            row=2, column=0, sticky="w", pady=(8, 0)
        )
        ttk.Checkbutton(options, text="Download thumbnails", variable=self.download_thumbs_var, command=self.toggle_downloads).grid(
            row=2, column=1, sticky="w", pady=(8, 0)
        )

        ttk.Label(options, text="Quality").grid(row=3, column=0, sticky="w", pady=(6, 0))
        self.quality_var = tk.StringVar(value="best")
        self.quality_combo = ttk.Combobox(
            options,
            textvariable=self.quality_var,
            values=["best", "1080p", "720p"],
            state="readonly",
            width=10,
        )
        self.quality_combo.grid(row=3, column=1, sticky="w", padx=6, pady=(6, 0))

        options.columnconfigure(1, weight=1)

        status = ttk.LabelFrame(right, text="Status", padding=8)
        status.pack(fill="both", expand=True, pady=(10, 0))
        self.status_label = ttk.Label(status, text="Idle")
        self.status_label.pack(anchor="w")
        self.progress = ttk.Progressbar(status, mode="indeterminate")
        self.progress.pack(fill="x", pady=(6, 0))

        footer = ttk.Frame(self.dialog, padding=8)
        footer.pack(fill="x")
        self.start_button = ttk.Button(footer, text="Start Import", command=self.start_import)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(footer, text="Stop", command=self.stop_import, state="disabled")
        self.stop_button.pack(side="left", padx=6)
        ttk.Button(footer, text="Close", command=self.dialog.destroy).pack(side="right")

        self.toggle_downloads()

    def set_status(self, text):
        self.status_label.config(text=text)

    def set_busy(self, busy: bool):
        state = "disabled" if busy else "normal"
        self.start_button.config(state=state)
        self.stop_button.config(state="normal" if busy else "disabled")
        if busy:
            self.progress.start(10)
        else:
            self.progress.stop()

    def browse_excel(self):
        path = filedialog.asksaveasfilename(
            title="Save Excel",
            defaultextension=".xlsx",
            filetypes=[("Excel Files", "*.xlsx"), ("All Files", "*.*")],
        )
        if path:
            self.excel_entry.delete(0, tk.END)
            self.excel_entry.insert(0, path)

    def browse_folder(self):
        path = filedialog.askdirectory(title="Select base download folder")
        if path:
            self.base_folder_entry.delete(0, tk.END)
            self.base_folder_entry.insert(0, path)

    def toggle_downloads(self):
        enabled = self.download_videos_var.get() or self.download_thumbs_var.get()
        state = "normal" if enabled else "disabled"
        self.base_folder_entry.config(state=state)
        self.quality_combo.config(state="readonly" if self.download_videos_var.get() else "disabled")

    def select_all(self):
        self.playlist_listbox.selection_set(0, tk.END)

    def clear_selection(self):
        self.playlist_listbox.selection_clear(0, tk.END)

    def fetch_playlists(self):
        raw = self.channel_entry.get().strip()
        if not raw:
            messagebox.showerror("Missing", "Please enter a channel URL or ID.", parent=self.dialog)
            return

        self.set_busy(True)
        self.set_status("Resolving channel...")

        def run():
            try:
                channel_id = resolve_channel_id(self.youtube, raw)
                playlists = fetch_playlists(self.youtube, channel_id)
                self.root.after(0, lambda: self.on_playlists_loaded(channel_id, playlists))
            except Exception as err:
                self.root.after(0, lambda: self.on_error(err))

        threading.Thread(target=run, daemon=True).start()

    def on_playlists_loaded(self, channel_id, playlists):
        self.channel_id = channel_id
        self.playlists = playlists
        self.playlist_listbox.delete(0, tk.END)

        for item in playlists:
            title = item.get("title", "")
            pid = item.get("id", "")
            count = item.get("item_count", "")
            suffix = f" | {count}" if count else ""
            self.playlist_listbox.insert(tk.END, f"{title} | {pid}{suffix}")

        self.set_busy(False)
        self.set_status(f"Loaded {len(playlists)} playlists.")

    def start_import(self):
        selections = list(self.playlist_listbox.curselection())
        if not selections:
            messagebox.showerror("No Selection", "Select at least one playlist.", parent=self.dialog)
            return

        excel_path = self.excel_entry.get().strip()
        if not excel_path:
            excel_path = os.path.join(DATA_DIR, "channel_export.xlsx")
            self.excel_entry.insert(0, excel_path)

        download_videos = self.download_videos_var.get()
        download_thumbs = self.download_thumbs_var.get()
        base_folder = self.base_folder_entry.get().strip()

        if download_videos and not messagebox.askyesno(
            "Permission Confirmation",
            "You confirm you have permission to download these videos.\nDo you want to continue?",
            parent=self.dialog,
        ):
            return

        if (download_videos or download_thumbs) and not base_folder:
            messagebox.showerror("Missing", "Select a base download folder.", parent=self.dialog)
            return

        playlist_map = {self.playlists[i]["id"]: self.playlists[i]["title"] for i in selections}
        quality = self.quality_var.get().strip() or "best"

        self.stop_event.clear()
        self.set_busy(True)
        self.set_status("Starting import...")

        def run():
            try:
                count = import_playlists(
                    youtube=self.youtube,
                    playlist_items_by_id=playlist_map,
                    excel_path=excel_path,
                    download_videos=download_videos,
                    download_thumbnails=download_thumbs,
                    base_download_dir=base_folder,
                    quality=quality,
                    progress_callback=self.on_progress,
                    stop_event=self.stop_event,
                )
                self.root.after(0, lambda: self.on_done(count, excel_path))
            except InterruptedError:
                self.root.after(0, self.on_cancelled)
            except Exception as err:
                self.root.after(0, lambda: self.on_error(err))

        threading.Thread(target=run, daemon=True).start()

    def stop_import(self):
        self.stop_event.set()
        self.set_status("Stopping...")

    def on_progress(self, phase, current, total, message):
        def apply():
            if phase == "playlist":
                self.set_status(f"Fetching playlist {current}/{total}: {message}")
            elif phase == "download":
                self.set_status(f"Downloading {current}/{total}: {message}")
        self.root.after(0, apply)

    def on_done(self, count, excel_path):
        self.set_busy(False)
        self.set_status(f"Done. Exported {count} rows.")
        messagebox.showinfo("Done", f"Saved {count} rows to:\n{excel_path}", parent=self.dialog)

    def on_cancelled(self):
        self.set_busy(False)
        self.set_status("Canceled.")
        messagebox.showinfo("Canceled", "Import canceled.", parent=self.dialog)

    def on_error(self, err):
        self.set_busy(False)
        self.set_status("Error")
        messagebox.showerror("Error", str(err), parent=self.dialog)
