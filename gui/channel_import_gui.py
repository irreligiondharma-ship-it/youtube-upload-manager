import os
import shutil
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import logging

from config.constants import DATA_DIR, STORAGE_DIR
from core.channel_importer import (
    extract_video_id,
    fetch_playlist_items,
    fetch_playlists,
    import_playlists,
    import_single_video,
    resolve_channel_id,
)


class ChannelImportGUI:
    def __init__(self, root, youtube_client):
        self.root = root
        self.youtube = youtube_client
        self.channel_id = ""
        self.playlists = []
        self.video_items = []
        self.video_playlist_id = ""
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
        self.playlist_listbox = tk.Listbox(left, selectmode="extended", exportselection=False)
        self.playlist_listbox.pack(fill="both", expand=True)

        playlist_buttons = ttk.Frame(left)
        playlist_buttons.pack(fill="x", pady=(6, 0))
        ttk.Button(playlist_buttons, text="Select All", command=self.select_all).pack(side="left")
        ttk.Button(playlist_buttons, text="Clear", command=self.clear_selection).pack(side="left", padx=6)

        video_header = ttk.Frame(left)
        video_header.pack(fill="x", pady=(10, 0))
        ttk.Label(video_header, text="Videos (optional)").pack(side="left")
        ttk.Button(video_header, text="Load Videos", command=self.load_videos).pack(side="right")

        self.video_listbox = tk.Listbox(left, selectmode="extended", height=8, exportselection=False)
        self.video_listbox.pack(fill="both", expand=False)

        video_buttons = ttk.Frame(left)
        video_buttons.pack(fill="x", pady=(4, 0))
        ttk.Button(video_buttons, text="Select All Videos", command=self.select_all_videos).pack(side="left")
        ttk.Button(video_buttons, text="Clear Videos", command=self.clear_videos).pack(side="left", padx=6)

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

        self.skip_existing_var = tk.BooleanVar(value=True)
        self.skip_existing_check = ttk.Checkbutton(
            options,
            text="Skip already downloaded",
            variable=self.skip_existing_var,
        )
        self.skip_existing_check.grid(row=2, column=2, sticky="w", pady=(8, 0))

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

        self.fast_mode_var = tk.BooleanVar(value=False)
        self.fast_mode_check = ttk.Checkbutton(
            options,
            text="Fast mode (aria2c if installed)",
            variable=self.fast_mode_var,
        )
        self.fast_mode_check.grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))

        self.use_cookies_var = tk.BooleanVar(value=False)
        self.cookies_browser_var = tk.StringVar(value="edge")
        self.cookies_check = ttk.Checkbutton(
            options,
            text="Use browser cookies",
            variable=self.use_cookies_var,
            command=self.toggle_cookies,
        )
        self.cookies_check.grid(row=5, column=0, sticky="w", pady=(6, 0))
        self.cookies_combo = ttk.Combobox(
            options,
            textvariable=self.cookies_browser_var,
            values=["edge", "chrome", "firefox", "brave", "opera"],
            state="disabled",
            width=12,
        )
        self.cookies_combo.grid(row=5, column=1, sticky="w", padx=6, pady=(6, 0))
        self.cookies_file_var = tk.StringVar(value="")
        ttk.Label(options, text="Cookies file (optional)").grid(row=6, column=0, sticky="w", pady=(6, 0))
        self.cookies_file_entry = ttk.Entry(options, textvariable=self.cookies_file_var, state="disabled")
        self.cookies_file_entry.grid(row=6, column=1, sticky="we", padx=6, pady=(6, 0))
        ttk.Button(options, text="Browse", command=self.browse_cookies_file).grid(row=6, column=2, pady=(6, 0))

        options.columnconfigure(1, weight=1)

        single = ttk.LabelFrame(right, text="Single Video", padding=8)
        single.pack(fill="x", pady=(10, 0))
        ttk.Label(single, text="Video URL/ID").grid(row=0, column=0, sticky="w")
        self.single_entry = ttk.Entry(single)
        self.single_entry.grid(row=0, column=1, sticky="we", padx=6)
        ttk.Button(single, text="Download Single", command=self.start_single_video).grid(row=0, column=2)
        single.columnconfigure(1, weight=1)

        status = ttk.LabelFrame(right, text="Status", padding=8)
        status.pack(fill="both", expand=True, pady=(10, 0))
        self.status_label = ttk.Label(status, text="Idle")
        self.status_label.pack(anchor="w")
        self.current_item_label = ttk.Label(status, text="")
        self.current_item_label.pack(anchor="w", pady=(4, 0))
        self.video_progress = ttk.Progressbar(status, maximum=100)
        self.video_progress.pack(fill="x", pady=(4, 0))
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
        self.toggle_cookies()

    def _audit(self, event, level=logging.INFO, **details):
        parts = [f"event={event}"]
        for key, value in details.items():
            if value is None:
                continue
            text = str(value)
            if len(text) > 120:
                text = text[:117] + "..."
            parts.append(f"{key}={text}")
        logging.log(level, "AUDIT_IMPORT | %s", " | ".join(parts))

    def set_status(self, text):
        self.status_label.config(text=text)

    def set_busy(self, busy: bool):
        state = "disabled" if busy else "normal"
        self.start_button.config(state=state)
        self.stop_button.config(state="normal" if busy else "disabled")
        self.channel_entry.config(state=state)
        self.playlist_listbox.config(state=state)
        self.video_listbox.config(state=state)
        self.single_entry.config(state=state)
        self.video_progress["value"] = 0
        self.current_item_label.config(text="")
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
            self._audit("browse_excel", path=path)
            self.excel_entry.delete(0, tk.END)
            self.excel_entry.insert(0, path)
        else:
            self._audit("browse_excel_cancelled")

    def browse_folder(self):
        path = filedialog.askdirectory(title="Select base download folder")
        if path:
            self._audit("browse_folder", path=path)
            self.base_folder_entry.delete(0, tk.END)
            self.base_folder_entry.insert(0, path)
        else:
            self._audit("browse_folder_cancelled")

    def toggle_downloads(self):
        enabled = self.download_videos_var.get() or self.download_thumbs_var.get()
        state = "normal" if enabled else "disabled"
        self.base_folder_entry.config(state=state)
        download_videos = self.download_videos_var.get()
        self.quality_combo.config(state="readonly" if download_videos else "disabled")
        self.fast_mode_check.config(state="normal" if download_videos else "disabled")
        self.skip_existing_check.config(state="normal" if download_videos else "disabled")
        if not download_videos:
            self.fast_mode_var.set(False)
            self.use_cookies_var.set(False)
        self.cookies_check.config(state="normal" if download_videos else "disabled")
        self.toggle_cookies()
        self._audit(
            "toggle_downloads",
            download_videos=self.download_videos_var.get(),
            download_thumbnails=self.download_thumbs_var.get(),
            fast_mode=self.fast_mode_var.get(),
            skip_existing=self.skip_existing_var.get(),
        )

    def toggle_cookies(self):
        enabled = self.use_cookies_var.get()
        state = "readonly" if enabled else "disabled"
        self.cookies_combo.config(state=state)
        self.cookies_file_entry.config(state="normal" if enabled else "disabled")
        self._audit("toggle_cookies", enabled=enabled, browser=self.cookies_browser_var.get())

    def browse_cookies_file(self):
        path = filedialog.askopenfilename(
            title="Select cookies.txt",
            filetypes=[("Cookies File", "*.txt"), ("All Files", "*.*")],
        )
        if path:
            self.cookies_file_var.set(path)
            self._audit("browse_cookies_file", path=path)
        else:
            self._audit("browse_cookies_file_cancelled")

    def select_all(self):
        self._audit("select_all_playlists")
        self.playlist_listbox.selection_set(0, tk.END)

    def clear_selection(self):
        self._audit("clear_playlists_selection")
        self.playlist_listbox.selection_clear(0, tk.END)

    def clear_videos(self):
        self._audit("clear_videos_selection")
        self.video_items = []
        self.video_playlist_id = ""
        self.video_listbox.delete(0, tk.END)

    def select_all_videos(self):
        self._audit("select_all_videos")
        self.video_listbox.selection_set(0, tk.END)

    def load_videos(self):
        selections = list(self.playlist_listbox.curselection())
        if len(selections) != 1:
            self._audit("load_videos_invalid_selection", level=logging.WARNING, selected=len(selections))
            messagebox.showerror("Select One", "Select exactly one playlist to load videos.", parent=self.dialog)
            return

        playlist = self.playlists[selections[0]]
        playlist_id = playlist.get("id", "")
        playlist_title = playlist.get("title", "")
        if not playlist_id:
            self._audit("load_videos_missing_playlist_id", level=logging.ERROR)
            messagebox.showerror("Invalid", "Playlist ID missing.", parent=self.dialog)
            return

        self._audit("load_videos_start", playlist_id=playlist_id, playlist_title=playlist_title)
        self.set_busy(True)
        self.set_status(f"Loading videos for: {playlist_title}")

        def run():
            try:
                items = fetch_playlist_items(self.youtube, playlist_id, playlist_title)
                self.root.after(0, lambda: self.on_videos_loaded(playlist_id, items))
            except Exception as err:
                self.root.after(0, lambda err=err: self.on_error(err))

        threading.Thread(target=run, daemon=True).start()

    def fetch_playlists(self):
        raw = self.channel_entry.get().strip()
        if not raw:
            self._audit("fetch_playlists_missing_channel", level=logging.WARNING)
            messagebox.showerror("Missing", "Please enter a channel URL or ID.", parent=self.dialog)
            return

        self._audit("fetch_playlists_start", channel_input=raw)
        self.set_busy(True)
        self.set_status("Resolving channel...")

        def run():
            try:
                channel_id = resolve_channel_id(self.youtube, raw)
                playlists = fetch_playlists(self.youtube, channel_id)
                self.root.after(0, lambda: self.on_playlists_loaded(channel_id, playlists))
            except Exception as err:
                self.root.after(0, lambda err=err: self.on_error(err))

        threading.Thread(target=run, daemon=True).start()

    def on_playlists_loaded(self, channel_id, playlists):
        self.channel_id = channel_id
        self.playlists = playlists
        self.playlist_listbox.delete(0, tk.END)
        self.playlist_listbox.config(state="normal")
        self.playlist_listbox.focus_set()
        self.clear_videos()

        for item in playlists:
            title = item.get("title", "")
            pid = item.get("id", "")
            count = item.get("item_count", "")
            suffix = f" | {count}" if count else ""
            self.playlist_listbox.insert(tk.END, f"{title} | {pid}{suffix}")

        self._audit("playlists_loaded", channel_id=channel_id, count=len(playlists))
        self.set_busy(False)
        self.dialog.update_idletasks()
        self.set_status(f"Loaded {len(playlists)} playlists.")

    def on_videos_loaded(self, playlist_id, items):
        self.video_items = items
        self.video_playlist_id = playlist_id
        self.video_listbox.delete(0, tk.END)
        self.video_listbox.config(state="normal")
        self.video_listbox.focus_set()
        for item in items:
            title = item.get("title", "")
            vid = item.get("video_id", "")
            self.video_listbox.insert(tk.END, f"{title} | {vid}")

        self._audit("videos_loaded", playlist_id=playlist_id, count=len(items))
        self.set_busy(False)
        self.dialog.update_idletasks()
        self.set_status(f"Loaded {len(items)} videos.")

    def start_import(self):
        selections = list(self.playlist_listbox.curselection())
        if not selections:
            self._audit("start_import_no_selection", level=logging.WARNING)
            messagebox.showerror("No Selection", "Select at least one playlist.", parent=self.dialog)
            return

        excel_path = self.excel_entry.get().strip()
        if not excel_path:
            excel_path = os.path.join(DATA_DIR, "channel_export.xlsx")
            self.excel_entry.insert(0, excel_path)

        download_videos = self.download_videos_var.get()
        download_thumbs = self.download_thumbs_var.get()
        base_folder = self.base_folder_entry.get().strip()
        use_aria2c = self.fast_mode_var.get()
        skip_existing = self.skip_existing_var.get()
        cookies_from_browser = self.cookies_browser_var.get().strip() if self.use_cookies_var.get() else None
        cookie_file = self.cookies_file_var.get().strip() if self.use_cookies_var.get() else ""
        if self.use_cookies_var.get() and cookie_file and not os.path.isfile(cookie_file):
            self._audit("start_import_cookie_file_missing", level=logging.WARNING, path=cookie_file)
            messagebox.showerror("Missing", f"Cookies file not found:\n{cookie_file}", parent=self.dialog)
            return

        if download_videos and not messagebox.askyesno(
            "Permission Confirmation",
            "You confirm you have permission to download these videos.\nDo you want to continue?",
            parent=self.dialog,
        ):
            self._audit("start_import_cancelled", reason="permission_denied")
            return

        if (download_videos or download_thumbs) and not base_folder:
            self._audit("start_import_missing_base_folder", level=logging.WARNING)
            messagebox.showerror("Missing", "Select a base download folder.", parent=self.dialog)
            return

        if use_aria2c and not shutil.which("aria2c"):
            self._audit("start_import_aria2c_missing", level=logging.WARNING)
            messagebox.showwarning(
                "aria2c Not Found",
                "Fast mode requires aria2c, but it was not found on this system.\n"
                "Falling back to the default downloader.",
                parent=self.dialog,
            )
            use_aria2c = False

        playlist_map = {self.playlists[i]["id"]: self.playlists[i]["title"] for i in selections}
        selected_videos = list(self.video_listbox.curselection())
        video_filter_map = None
        if selected_videos:
            if len(selections) != 1:
                self._audit("start_import_video_filter_invalid", level=logging.WARNING)
                messagebox.showerror(
                    "Video Filter",
                    "Select exactly one playlist when filtering by individual videos.",
                    parent=self.dialog,
                )
                return
            playlist_id = self.playlists[selections[0]].get("id", "")
            if playlist_id != self.video_playlist_id:
                self._audit("start_import_video_filter_mismatch", level=logging.WARNING)
                messagebox.showerror(
                    "Video Filter",
                    "Loaded videos are from a different playlist. Please reload videos.",
                    parent=self.dialog,
                )
                return
            video_filter_map = {
                playlist_id: {self.video_items[i].get("video_id", "") for i in selected_videos}
            }
        quality = self.quality_var.get().strip() or "best"

        self._audit(
            "start_import",
            playlists=len(selections),
            download_videos=download_videos,
            download_thumbnails=download_thumbs,
            base_folder=base_folder,
            quality=quality,
            fast_mode=use_aria2c,
            skip_existing=skip_existing,
            filtered_videos=len(selected_videos),
            cookies_from_browser=cookies_from_browser or "",
            cookie_file=bool(cookie_file),
        )
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
                    use_aria2c=use_aria2c,
                    cookies_from_browser=cookies_from_browser,
                    cookie_file=cookie_file or None,
                    skip_existing=skip_existing,
                    video_filter_map=video_filter_map,
                    progress_callback=self.on_progress,
                    stop_event=self.stop_event,
                )
                self.root.after(0, lambda: self.on_done(count, excel_path))
            except InterruptedError:
                self.root.after(0, self.on_cancelled)
            except Exception as err:
                self.root.after(0, lambda err=err: self.on_error(err))

        threading.Thread(target=run, daemon=True).start()

    def start_single_video(self):
        video_input = self.single_entry.get().strip()
        if not video_input:
            self._audit("start_single_missing_input", level=logging.WARNING)
            messagebox.showerror("Missing", "Enter a video URL or ID.", parent=self.dialog)
            return

        if not extract_video_id(video_input):
            self._audit("start_single_invalid_input", level=logging.WARNING, input=video_input)
            messagebox.showerror("Invalid", "Could not detect a valid video ID.", parent=self.dialog)
            return

        excel_path = self.excel_entry.get().strip()
        if not excel_path:
            excel_path = os.path.join(DATA_DIR, "channel_export.xlsx")
            self.excel_entry.insert(0, excel_path)

        download_videos = self.download_videos_var.get()
        download_thumbs = self.download_thumbs_var.get()
        base_folder = self.base_folder_entry.get().strip()
        use_aria2c = self.fast_mode_var.get()
        skip_existing = self.skip_existing_var.get()
        cookies_from_browser = self.cookies_browser_var.get().strip() if self.use_cookies_var.get() else None
        cookie_file = self.cookies_file_var.get().strip() if self.use_cookies_var.get() else ""
        if self.use_cookies_var.get() and cookie_file and not os.path.isfile(cookie_file):
            self._audit("start_single_cookie_file_missing", level=logging.WARNING, path=cookie_file)
            messagebox.showerror("Missing", f"Cookies file not found:\n{cookie_file}", parent=self.dialog)
            return

        if not download_videos:
            self._audit("start_single_missing_download", level=logging.WARNING)
            messagebox.showerror("Missing", "Enable 'Download videos' for single video.", parent=self.dialog)
            return

        if download_videos and not messagebox.askyesno(
            "Permission Confirmation",
            "You confirm you have permission to download this video.\nDo you want to continue?",
            parent=self.dialog,
        ):
            self._audit("start_single_cancelled", reason="permission_denied")
            return

        if (download_videos or download_thumbs) and not base_folder:
            self._audit("start_single_missing_base_folder", level=logging.WARNING)
            messagebox.showerror("Missing", "Select a base download folder.", parent=self.dialog)
            return

        if use_aria2c and not shutil.which("aria2c"):
            self._audit("start_single_aria2c_missing", level=logging.WARNING)
            messagebox.showwarning(
                "aria2c Not Found",
                "Fast mode requires aria2c, but it was not found on this system.\n"
                "Falling back to the default downloader.",
                parent=self.dialog,
            )
            use_aria2c = False

        quality = self.quality_var.get().strip() or "best"

        self._audit(
            "start_single",
            input=video_input,
            download_videos=download_videos,
            download_thumbnails=download_thumbs,
            base_folder=base_folder,
            quality=quality,
            fast_mode=use_aria2c,
            skip_existing=skip_existing,
            cookies_from_browser=cookies_from_browser or "",
            cookie_file=bool(cookie_file),
        )
        self.stop_event.clear()
        self.set_busy(True)
        self.set_status("Starting single video download...")

        def run():
            try:
                count = import_single_video(
                    youtube=self.youtube,
                    video_input=video_input,
                    excel_path=excel_path,
                    download_videos=download_videos,
                    download_thumbnails=download_thumbs,
                    base_download_dir=base_folder,
                    quality=quality,
                    use_aria2c=use_aria2c,
                    cookies_from_browser=cookies_from_browser,
                    cookie_file=cookie_file or None,
                    skip_existing=skip_existing,
                    progress_callback=self.on_progress,
                    stop_event=self.stop_event,
                )
                self.root.after(0, lambda: self.on_done(count, excel_path))
            except InterruptedError:
                self.root.after(0, self.on_cancelled)
            except Exception as err:
                self.root.after(0, lambda err=err: self.on_error(err))

        threading.Thread(target=run, daemon=True).start()

    def stop_import(self):
        self._audit("stop_import_clicked")
        self.stop_event.set()
        self.set_status("Stopping...")

    def on_progress(self, phase, current, total, message, percent=None):
        def apply():
            if phase == "playlist":
                self.set_status(f"Fetching playlist {current}/{total}: {message}")
            elif phase == "download":
                self.set_status(f"Downloading {current}/{total}: {message}")
                self.current_item_label.config(text=f"Current: {message}")
                if percent is not None:
                    self.video_progress["value"] = percent
                else:
                    self.video_progress["value"] = 0
        self.root.after(0, apply)

    def on_done(self, summary, excel_path):
        self.set_busy(False)
        self.set_status("Status: Idle")
        self.current_item_label.config(text="")
        self.video_progress["value"] = 0
        
        # Handle summary counts
        total = 0
        success = 0
        failed = 0
        skipped = 0
        
        if isinstance(summary, dict):
            total = summary.get("total", 0)
            success = summary.get("downloaded", 0)
            failed = summary.get("failed", 0)
            skipped = summary.get("skipped", 0)
        else:
            # Fallback for old integer return
            total = summary

        msg = (
            f"Import Process Completed!\n\n"
            f"Total Videos Processed: {total}\n"
            f"Successfully Downloaded/Imported: {success}\n"
            f"Failed: {failed}\n"
            f"Skipped (Already exists): {skipped}\n\n"
            f"Excel file updated: {os.path.basename(excel_path)}"
        )

        self._audit("import_done_summary", total=total, success=success, failed=failed, skipped=skipped)
        
        if failed > 0:
            messagebox.showwarning("Import Summary", msg, parent=self.dialog)
        else:
            messagebox.showinfo("Import Summary", msg, parent=self.dialog)

    def on_cancelled(self):
        self.set_busy(False)
        self.set_status("Canceled.")
        self.current_item_label.config(text="")
        self.video_progress["value"] = 0
        self._audit("import_cancelled", level=logging.WARNING)
        messagebox.showinfo("Canceled", "Import canceled.", parent=self.dialog)

    def on_error(self, err):
        self.set_busy(False)
        self.set_status("Error")
        self.current_item_label.config(text="")
        self.video_progress["value"] = 0
        self._audit("import_error", level=logging.ERROR, error=str(err))
        messagebox.showerror("Error", str(err), parent=self.dialog)
