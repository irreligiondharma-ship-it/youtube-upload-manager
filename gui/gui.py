import tkinter as tk
from tkinter import filedialog, ttk, messagebox
from PIL import Image, ImageTk
import logging
import os
import time

from config.constants import APP_NAME, WINDOW_WIDTH, WINDOW_HEIGHT, EXCEL_FILE, VIDEOS_DIR, THUMBNAILS_DIR
from core.account_manager import AccountManager
from core.upload_worker import UploadWorker
from core.excel_manager import ExcelManager
from core.input_config import load_input_sources, save_input_sources, save_last_account
from gui.channel_manager_gui import ChannelManagerGUI
from gui.channel_import_gui import ChannelImportGUI


class YouTubeUploadGUI:

    REFRESH_INTERVAL = 1000
    QUEUE_REFRESH_INTERVAL_MS = 3000
    MAX_THUMBNAIL_BYTES = 10 * 1024 * 1024

    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.root.resizable(True, True)

        self.account_manager = AccountManager()
        self.upload_worker = None

        sources = load_input_sources()
        self.selected_excel_file = sources.get("excel_file", EXCEL_FILE)
        self.selected_videos_dir = sources.get("videos_dir", VIDEOS_DIR)
        self.selected_thumbnails_dir = sources.get("thumbnails_dir", THUMBNAILS_DIR)
        self.last_account_name = sources.get("last_account", "")

        self.excel = ExcelManager(excel_file=self.selected_excel_file, videos_dir=self.selected_videos_dir)

        self.thumbnail_image = None
        self._worker_finished_notified = False
        self.is_paused = False
        self.current_upload_index = None
        self._queue_cache = []
        self._last_queue_refresh = 0.0

        self.create_layout()
        self.load_accounts()
        self.refresh_queue()
        self.refresh_stats()

        self.root.after(self.REFRESH_INTERVAL, self.auto_refresh)
        
        # Connect window close protocol
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def on_close(self):
        """Handle window close event gracefully."""
        if self.upload_worker and self.upload_worker.is_alive():
            confirm = messagebox.askyesno(
                "Exit Application",
                "An upload is currently in progress. Stopping now may leave the current video in an incomplete state.\n\nDo you want to stop the upload and exit?",
                parent=self.root
            )
            if not confirm:
                self._audit("exit_cancelled", reason="upload_running")
                return
            
            self._audit("exit_confirmed_stopping_worker")
            self.upload_worker.stop()
            # Wait a moment for the worker to signal stopping
            time.sleep(0.5)

        # Final flush of excel changes
        try:
            self.excel.flush_pending_save()
        except:
            pass
            
        self._audit("app_exit")
        self.root.destroy()

    def _audit(self, event, level=logging.INFO, **details):
        parts = [f"event={event}"]
        for key, value in details.items():
            if value is None:
                continue
            text = str(value)
            if len(text) > 120:
                text = text[:117] + "..."
            parts.append(f"{key}={text}")
        logging.log(level, "AUDIT_GUI | %s", " | ".join(parts))

    # ===============================
    # Layout
    # ===============================
    def create_layout(self):

        top = ttk.Frame(self.root, padding=5)
        top.pack(fill="x")

        self.account_label = ttk.Label(top, text="Account: None")
        self.account_label.pack(side="left")

        ttk.Button(top, text="Change Account",
                   command=self.change_account).pack(side="right", padx=5)
        ttk.Button(top, text="Remove Account",
                   command=self.remove_account).pack(side="right", padx=5)
        ttk.Button(top, text="Channel Import",
                   command=self.open_channel_import).pack(side="right", padx=5)
        ttk.Button(top, text="Channel Manager",
                   command=self.open_channel_manager).pack(side="right", padx=5)
        ttk.Button(top, text="Add Account",
                   command=self.add_account).pack(side="right")

        sources = ttk.LabelFrame(self.root, text="Input Sources", padding=5)
        sources.pack(fill="x", padx=5)

        ttk.Button(sources, text="Select Excel", command=self.select_excel_file).grid(row=0, column=0, padx=3, pady=2, sticky="w")
        ttk.Button(sources, text="Select Videos Folder", command=self.select_videos_folder).grid(row=1, column=0, padx=3, pady=2, sticky="w")
        ttk.Button(sources, text="Select Thumbnails Folder", command=self.select_thumbnails_folder).grid(row=2, column=0, padx=3, pady=2, sticky="w")
        ttk.Button(sources, text="Validate Sources", command=self.validate_sources).grid(row=0, column=2, padx=3, pady=2, sticky="w")
        ttk.Button(sources, text="Reset Defaults", command=self.reset_sources_to_defaults).grid(row=1, column=2, padx=3, pady=2, sticky="w")

        self.excel_path_label = ttk.Label(sources, text="")
        self.excel_path_label.grid(row=0, column=1, sticky="w")
        self.videos_path_label = ttk.Label(sources, text="")
        self.videos_path_label.grid(row=1, column=1, sticky="w")
        self.thumbs_path_label = ttk.Label(sources, text="")
        self.thumbs_path_label.grid(row=2, column=1, sticky="w")

        self.refresh_source_labels()

        main = ttk.Frame(self.root)
        main.pack(fill="both", expand=True)

        # LEFT - Queue
        left = ttk.Frame(main, padding=5)
        left.pack(side="left", fill="both", expand=True)

        ttk.Label(left, text="Upload Queue").pack(anchor="w")

        self.queue_listbox = tk.Listbox(left)
        self.queue_listbox.pack(fill="both", expand=True)
        self.queue_listbox.bind("<<ListboxSelect>>", self.show_preview)

        # RIGHT
        right = ttk.Frame(main, padding=5)
        right.pack(side="right", fill="both", expand=True)

        preview = ttk.LabelFrame(right, text="Preview", padding=5)
        preview.pack(fill="x")

        self.thumbnail_label = ttk.Label(preview)
        self.thumbnail_label.pack()

        self.details_text = tk.Text(preview, height=6)
        self.details_text.pack(fill="x")

        status = ttk.LabelFrame(right, text="Status", padding=5)
        status.pack(fill="both", expand=True)

        self.stats_label = ttk.Label(status, text="")
        self.stats_label.pack(anchor="w")
        self.worker_state_label = ttk.Label(status, text="Upload State: Idle")
        self.worker_state_label.pack(anchor="w")
        self.current_upload_label = ttk.Label(status, text="Now Uploading: None")
        self.current_upload_label.pack(anchor="w")

        ttk.Label(status, text="Current Video Progress").pack(anchor="w")
        self.current_video_progress = ttk.Progressbar(status, maximum=100)
        self.current_video_progress.pack(fill="x", pady=(0, 5))

        ttk.Label(status, text="Overall Queue Progress").pack(anchor="w")
        self.overall_progress = ttk.Progressbar(status, maximum=100)
        self.overall_progress.pack(fill="x", pady=(0, 5))

        self.log_text = tk.Text(status, height=5)
        self.log_text.pack(fill="both", expand=True)

        bottom = ttk.Frame(self.root, padding=5)
        bottom.pack(fill="x")

        self.start_button = ttk.Button(bottom, text="Start", command=self.start_upload)
        self.start_button.pack(side="left", padx=5)
        self.pause_resume_button = ttk.Button(bottom, text="Pause", command=self.toggle_pause_resume, state="disabled")
        self.pause_resume_button.pack(side="left", padx=5)
        self.stop_button = ttk.Button(bottom, text="Stop", command=self.stop_upload, state="disabled")
        self.stop_button.pack(side="left", padx=5)

    # ===============================
    # Account Handling
    # ===============================
    def load_accounts(self):
        accounts = sorted(self.account_manager.list_accounts())
        if accounts:
            target = self.last_account_name if self.last_account_name in accounts else accounts[0]
            try:
                self.account_manager.validate_account(target)
                self.account_label.config(text=f"Account: {target}")
                self._audit("load_accounts", account=target, count=len(accounts))
            except Exception:
                self.account_label.config(text="Account: None")
                self._audit("load_accounts_reauth_required", level=logging.WARNING, account=target)
                self.show_reauth_prompt(target)
        else:
            self._audit("load_accounts_empty", level=logging.INFO)

    def add_account(self):
        self._audit("add_account_clicked")
        try:
            name = self.account_manager.add_account()
            self.account_manager.load_account(name)
            self.account_label.config(text=f"Account: {name}")
            save_last_account(name)
            self.last_account_name = name
            self._audit("add_account_success", account=name)
            messagebox.showinfo("Success", f"Account added: {name}")
        except Exception as e:
            self._audit("add_account_failed", level=logging.ERROR, error=str(e))
            messagebox.showerror("Error", str(e))

    def open_channel_manager(self):
        if not self.account_manager.youtube:
            self._audit("open_channel_manager_failed", level=logging.WARNING, reason="no_account")
            messagebox.showerror("Error", "No account loaded.")
            return
        self._audit("open_channel_manager")
        ChannelManagerGUI(
            self.root,
            youtube_client=self.account_manager.youtube,
            account_name=self.account_manager.get_current_account() or "",
            account_manager=self.account_manager,
        )

    def open_channel_import(self):
        if not self.account_manager.youtube:
            self._audit("open_channel_import_failed", level=logging.WARNING, reason="no_account")
            messagebox.showerror("Error", "No account loaded.")
            return
        self._audit("open_channel_import")
        ChannelImportGUI(self.root, youtube_client=self.account_manager.youtube)

    def remove_account(self):
        accounts = sorted(self.account_manager.list_accounts())
        if not accounts:
            self._audit("remove_account_no_accounts", level=logging.WARNING)
            messagebox.showwarning("No Accounts", "No accounts found.")
            return

        current = self.account_manager.get_current_account() or ""
        self._audit("remove_account_opened", current=current)

        dialog = tk.Toplevel(self.root)
        dialog.title("Remove Account")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        container = ttk.Frame(dialog, padding=10)
        container.pack(fill="both", expand=True)

        ttk.Label(container, text="Select account to remove:").grid(row=0, column=0, sticky="w")

        selected = tk.StringVar(value=current if current in accounts else accounts[0])
        combo = ttk.Combobox(
            container,
            textvariable=selected,
            values=accounts,
            state="readonly",
            width=40,
        )
        combo.grid(row=1, column=0, pady=5, sticky="we")
        combo.focus_set()

        buttons = ttk.Frame(container)
        buttons.grid(row=2, column=0, sticky="e")

        def on_cancel():
            self._audit("remove_account_cancelled")
            dialog.destroy()

        def on_remove():
            choice = selected.get().strip()
            if not choice:
                self._audit("remove_account_invalid", level=logging.WARNING)
                messagebox.showerror("Invalid", "Please select an account.", parent=dialog)
                return

            confirm = messagebox.askyesno(
                "Confirm Remove",
                f"Remove account '{choice}' from this app?\nThis does not delete your YouTube channel.",
                parent=dialog,
            )
            if not confirm:
                self._audit("remove_account_declined", account=choice)
                return

            try:
                self.account_manager.remove_account(choice)
                if choice == self.last_account_name:
                    self.last_account_name = ""
                    save_last_account("")
                self.account_label.config(text="Account: None")
                dialog.destroy()
                self._audit("remove_account_success", account=choice)
                messagebox.showinfo("Success", f"Removed account: {choice}")
                self.load_accounts()
            except Exception as err:
                self._audit("remove_account_failed", level=logging.ERROR, account=choice, error=str(err))
                messagebox.showerror("Error", str(err), parent=dialog)

        ttk.Button(buttons, text="Cancel", command=on_cancel).pack(side="right", padx=(5, 0))
        ttk.Button(buttons, text="Remove", command=on_remove).pack(side="right")

        dialog.bind("<Return>", lambda _e: on_remove())
        dialog.bind("<Escape>", lambda _e: on_cancel())

    def change_account(self):
        accounts = sorted(self.account_manager.list_accounts())
        if not accounts:
            self._audit("change_account_no_accounts", level=logging.WARNING)
            messagebox.showwarning("No Accounts", "No accounts found.")
            return

        current = self.account_manager.get_current_account() or ""
        self._audit("change_account_opened", current=current)

        dialog = tk.Toplevel(self.root)
        dialog.title("Change Account")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        container = ttk.Frame(dialog, padding=10)
        container.pack(fill="both", expand=True)

        ttk.Label(container, text="Select account:").grid(row=0, column=0, sticky="w")

        selected = tk.StringVar(value=current if current in accounts else accounts[0])
        combo = ttk.Combobox(
            container,
            textvariable=selected,
            values=accounts,
            state="readonly",
            width=40,
        )
        combo.grid(row=1, column=0, pady=5, sticky="we")
        combo.focus_set()

        current_text = current if current else "None"
        ttk.Label(container, text=f"Current: {current_text}").grid(
            row=2, column=0, sticky="w", pady=(0, 8)
        )

        buttons = ttk.Frame(container)
        buttons.grid(row=3, column=0, sticky="e")

        def on_cancel():
            self._audit("change_account_cancelled")
            dialog.destroy()

        def on_select():
            choice = selected.get().strip()
            if not choice:
                self._audit("change_account_invalid", level=logging.WARNING)
                messagebox.showerror("Invalid", "Please select an account.", parent=dialog)
                return

            if choice == current:
                dialog.destroy()
                self._audit("change_account_same", account=choice)
                messagebox.showinfo("Info", f"Already using account: {choice}")
                return

            try:
                self.account_manager.validate_account(choice)
                self.account_label.config(text=f"Account: {choice}")
                save_last_account(choice)
                self.last_account_name = choice
                dialog.destroy()
                self._audit("change_account_success", account=choice)
                messagebox.showinfo("Success", f"Loaded account: {choice}")
            except Exception:
                dialog.destroy()
                self._audit("change_account_reauth_required", level=logging.WARNING, account=choice)
                self.show_reauth_prompt(choice)

        ttk.Button(buttons, text="Cancel", command=on_cancel).pack(side="right", padx=(5, 0))
        ttk.Button(buttons, text="Select", command=on_select).pack(side="right")

        dialog.bind("<Return>", lambda _e: on_select())
        dialog.bind("<Escape>", lambda _e: on_cancel())

    # ===============================
    # Input Sources
    # ===============================
    def refresh_source_labels(self):
        self.excel_path_label.config(text=f"Excel: {self.selected_excel_file}")
        self.videos_path_label.config(text=f"Videos: {self.selected_videos_dir}")
        self.thumbs_path_label.config(text=f"Thumbnails: {self.selected_thumbnails_dir}")

    def apply_selected_sources(self):
        self._audit(
            "apply_selected_sources",
            excel_file=self.selected_excel_file,
            videos_dir=self.selected_videos_dir,
            thumbnails_dir=self.selected_thumbnails_dir,
        )
        self.excel = ExcelManager(excel_file=self.selected_excel_file, videos_dir=self.selected_videos_dir)
        save_input_sources(
            excel_file=self.selected_excel_file,
            videos_dir=self.selected_videos_dir,
            thumbnails_dir=self.selected_thumbnails_dir,
            last_account=self.account_manager.get_current_account() or self.last_account_name,
        )
        self.refresh_source_labels()
        self.refresh_queue(reload=False)
        self.refresh_stats(reload=False)

    def select_excel_file(self):
        path = filedialog.askopenfilename(
            title="Select upload queue Excel",
            filetypes=[("Excel Files", "*.xlsx *.xls"), ("All Files", "*.*")],
            initialfile=os.path.basename(self.selected_excel_file),
        )
        if path:
            self._audit("select_excel_file", path=path)
            self.selected_excel_file = path
            self.apply_selected_sources()
        else:
            self._audit("select_excel_file_cancelled")

    def select_videos_folder(self):
        path = filedialog.askdirectory(title="Select videos folder", initialdir=self.selected_videos_dir)
        if path:
            self._audit("select_videos_folder", path=path)
            self.selected_videos_dir = path
            self.apply_selected_sources()
        else:
            self._audit("select_videos_folder_cancelled")

    def select_thumbnails_folder(self):
        path = filedialog.askdirectory(title="Select thumbnails folder", initialdir=self.selected_thumbnails_dir)
        if path:
            self._audit("select_thumbnails_folder", path=path)
            self.selected_thumbnails_dir = path
            self.apply_selected_sources()
        else:
            self._audit("select_thumbnails_folder_cancelled")

    def validate_sources(self):
        issues = []

        if not os.path.isfile(self.selected_excel_file):
            issues.append(f"Excel file not found: {self.selected_excel_file}")
        if not os.path.isdir(self.selected_videos_dir):
            issues.append(f"Videos folder not found: {self.selected_videos_dir}")
        if not os.path.isdir(self.selected_thumbnails_dir):
            issues.append(f"Thumbnails folder not found: {self.selected_thumbnails_dir}")

        if issues:
            self._audit("validate_sources_failed", level=logging.WARNING, issues="; ".join(issues))
            messagebox.showwarning("Input Sources Validation", "\n".join(issues))
        else:
            self._audit("validate_sources_ok")
            messagebox.showinfo("Input Sources Validation", "All selected input sources are valid.")

    def reset_sources_to_defaults(self):
        self._audit("reset_sources_to_defaults")
        self.selected_excel_file = EXCEL_FILE
        self.selected_videos_dir = VIDEOS_DIR
        self.selected_thumbnails_dir = THUMBNAILS_DIR
        self.apply_selected_sources()

    @staticmethod
    def _find_schedule_privacy_mismatches(df):
        mismatches = []
        for _, row in df.iterrows():
            schedule = str(row.get("schedule_time", "")).strip()
            privacy = str(row.get("privacy_status", "")).strip().lower()
            if schedule and privacy and privacy != "private":
                title = str(row.get("title", "")).strip()
                mismatches.append((title, privacy, schedule))
        return mismatches

    # ===============================
    # Preview (Fixed)
    # ===============================
    def show_preview(self, event):
        selection = self.queue_listbox.curselection()
        if not selection:
            return

        index = selection[0]
        row = self.excel.df.iloc[index]
        self._audit(
            "queue_row_selected",
            index=index,
            title=str(row.get("title", "")).strip(),
            status=str(row.get("status", "")).strip(),
        )

        self.details_text.delete("1.0", tk.END)
        details = (
            f"Title: {row.get('title')}\n"
            f"Status: {row.get('status')}\n"
            f"Privacy: {row.get('privacy_status')}\n"
            f"Playlist: {row.get('playlist')}"
        )
        self.details_text.insert(tk.END, details)

        thumb = row.get("thumbnail_path")

        if isinstance(thumb, str) and thumb.strip():
            abs_path = thumb if os.path.isabs(thumb) else os.path.join(self.selected_thumbnails_dir, thumb)
            if os.path.exists(abs_path):
                try:
                    if os.path.getsize(abs_path) > self.MAX_THUMBNAIL_BYTES:
                        self.thumbnail_label.config(image="")
                        return
                    with Image.open(abs_path) as img:
                        img.thumbnail((250, 140))
                        preview_img = img.copy()
                    self.thumbnail_image = ImageTk.PhotoImage(preview_img)
                    self.thumbnail_label.config(image=self.thumbnail_image)
                except OSError:
                    self.thumbnail_label.config(image="")
            else:
                self.thumbnail_label.config(image="")
        else:
            self.thumbnail_label.config(image="")

    # ===============================
    # Upload Controls
    # ===============================
    def start_upload(self):
        self._audit("start_upload_clicked")
        if not self.account_manager.youtube:
            self._audit("start_upload_failed", level=logging.ERROR, reason="no_account")
            messagebox.showerror("Error", "No account loaded.")
            return

        if self.upload_worker and self.upload_worker.is_alive():
            self._audit("start_upload_blocked", level=logging.WARNING, reason="already_running")
            messagebox.showwarning("Upload Running", "An upload is already running.")
            return

        pending = self.excel.get_pending_rows()
        if pending.empty:
            self._audit("start_upload_blocked", level=logging.WARNING, reason="no_pending_rows")
            messagebox.showinfo("No Pending Rows", "No pending uploads found in queue.")
            return

        if not self.warn_if_excel_open():
            self._audit("start_upload_cancelled", reason="excel_open")
            return

        mismatches = self._find_schedule_privacy_mismatches(pending)
        if mismatches:
            sample = []
            for title, privacy, schedule in mismatches[:3]:
                label = title or "Untitled"
                sample.append(f"- {label} (privacy: {privacy}, schedule: {schedule})")
            more = ""
            if len(mismatches) > 3:
                more = f"\n...and {len(mismatches) - 3} more"

            warning = (
                "Some rows have schedule_time but privacy is not private.\n"
                "YouTube only applies schedule when privacy is private.\n\n"
                f"Count: {len(mismatches)}\n"
                "Examples:\n"
                + "\n".join(sample)
                + more
                + "\n\nDo you want to continue?"
            )
            if not messagebox.askyesno("Schedule Warning", warning):
                self._audit("start_upload_cancelled", reason="schedule_privacy_mismatch")
                return

        self.upload_worker = UploadWorker(
            youtube_client=self.account_manager.youtube,
            account_name=self.account_manager.get_current_account(),
            progress_callback=self.update_progress,
            status_callback=self.handle_uploader_event,
            excel_file=self.selected_excel_file,
            videos_dir=self.selected_videos_dir,
            thumbnails_dir=self.selected_thumbnails_dir
        )
        self._worker_finished_notified = False
        self.is_paused = False
        self.current_upload_index = None
        self.upload_worker.start()
        self.set_controls_for_running()
        self.current_video_progress.configure(value=0)
        self.current_upload_label.config(text="Now Uploading: Preparing...")
        self._audit("start_upload_started", account=self.account_manager.get_current_account())
        self.log("Upload started.")

    def toggle_pause_resume(self):
        if not self.upload_worker or not self.upload_worker.is_alive():
            self._audit("pause_resume_ignored", level=logging.WARNING, reason="no_active_worker")
            return
        if self.is_paused:
            self.upload_worker.resume()
            self.is_paused = False
            self.pause_resume_button.config(text="Pause")
            self.worker_state_label.config(text="Upload State: Running")
            self._audit("resume_clicked")
            self.log("Resumed.")
            return
        self.upload_worker.pause()
        self.is_paused = True
        self.pause_resume_button.config(text="Resume")
        self.worker_state_label.config(text="Upload State: Paused")
        self._audit("pause_clicked")
        self.log("Paused.")

    def stop_upload(self):
        if not self.upload_worker or not self.upload_worker.is_alive():
            self._audit("stop_ignored", level=logging.WARNING, reason="no_active_worker")
            return

        confirm = messagebox.askyesno(
            "Stop Upload",
            "Are you sure you want to stop the upload process?\nCurrent upload will stop as soon as possible.",
        )
        if not confirm:
            self._audit("stop_cancelled")
            return

        self.upload_worker.stop()
        self.set_controls_for_stopping()
        self._audit("stop_requested")
        self.log("Stop requested.")

    # ===============================
    # Auto Refresh
    # ===============================
    def auto_refresh(self):
        try:
            self.excel.flush_pending_save()
            changed = self.excel.reload_if_changed()
            self.refresh_stats(reload=False)
            if changed:
                now = time.time()
                elapsed_ms = (now - self._last_queue_refresh) * 1000
                if elapsed_ms >= self.QUEUE_REFRESH_INTERVAL_MS:
                    self.refresh_queue(reload=False)
        except Exception as err:
            self._audit("auto_refresh_warning", level=logging.WARNING, error=str(err))
            self.log(f"Auto refresh warning: {err}")

        if self.upload_worker and not self.upload_worker.is_alive():
            self.set_controls_for_idle()
            if not self._worker_finished_notified:
                self.refresh_queue(reload=True, force=True)
                self.refresh_stats(reload=False)
                self.current_upload_index = None
                self.current_upload_label.config(text="Now Uploading: None")
                self.current_video_progress.configure(value=0)
                self._audit("worker_finished")
                self.log("Upload worker finished.")
                self._worker_finished_notified = True

        self.root.after(self.REFRESH_INTERVAL, self.auto_refresh)

    def refresh_queue(self, reload=True, force=False):
        if reload:
            self.excel.reload()
        display_rows = [
            f"{row.get('title')} [{row.get('status')}]"
            for _, row in self.excel.df.iterrows()
        ]
        if not force and display_rows == self._queue_cache:
            return
        self.queue_listbox.delete(0, tk.END)
        for display in display_rows:
            self.queue_listbox.insert(tk.END, display)
        self._queue_cache = display_rows
        self._last_queue_refresh = time.time()

    def refresh_stats(self, reload=True):
        if reload:
            self.excel.reload()
        stats = self.excel.get_stats()
        percent = 0
        if stats['total'] > 0:
            percent = int((stats['uploaded'] / stats['total']) * 100)

        self.overall_progress["value"] = percent

        text = (
            f"Total: {stats['total']} | "
            f"Uploaded: {stats['uploaded']} | "
            f"Pending: {stats['pending']} | "
            f"Failed: {stats['failed']} | "
            f"Skipped: {stats['skipped']}"
        )
        self.stats_label.config(text=text)

    def update_progress(self, value):
        # Called from worker thread; marshal UI update to Tk main thread
        self.root.after(0, lambda: self.current_video_progress.configure(value=value))

    def handle_uploader_event(self, event, payload):
        def _apply():
            if event == "state_change":
                state = payload.get("state", "")
                if state == "running":
                    self.worker_state_label.config(text="Upload State: Running")
                    if self.upload_worker and self.upload_worker.is_alive():
                        self.set_controls_for_running()
                    self._audit("uploader_state", state=state)
                elif state == "paused":
                    self.worker_state_label.config(text="Upload State: Paused")
                    self._audit("uploader_state", state=state)
                elif state == "stopping":
                    self.set_controls_for_stopping()
                    self.worker_state_label.config(text="Upload State: Stopping")
                    self._audit("uploader_state", state=state)
                elif state == "stopped":
                    self.set_controls_for_idle()
                    self.worker_state_label.config(text="Upload State: Stopped")
                    self._audit("uploader_state", state=state)
            elif event == "item_start":
                index = payload.get("index")
                title = payload.get("title", "")
                video_path = payload.get("video_path", "")
                self.current_upload_index = index
                self.current_video_progress.configure(value=0)
                self.current_upload_label.config(text=f"Now Uploading: {title} ({video_path})")
                self._audit("item_start", index=index, title=title, video_path=video_path)
                self.log(f"Uploading row {index}: {title}")
                self.select_queue_row_by_index(index)
            elif event == "item_done":
                index = payload.get("index")
                title = payload.get("title", "")
                video_id = payload.get("video_id", "")
                warning = payload.get("warning", "")
                self.current_video_progress.configure(value=100)
                self._audit("item_done", index=index, title=title, video_id=video_id, warning=warning)
                self.log(f"Uploaded row {index}: {title} ({video_id})")
                if warning:
                    self.log(f"Warning row {index}: {warning}")
            elif event == "item_failed":
                index = payload.get("index")
                title = payload.get("title", "")
                error = payload.get("error", "")
                self._audit("item_failed", level=logging.ERROR, index=index, title=title, error=error)
                self.log(f"Failed row {index}: {title} | {error}")
        self.root.after(0, _apply)

    def show_reauth_prompt(self, account_name):
        prompt = (
            f"Authentication for account '{account_name}' has expired or is invalid.\n"
            "Do you want to re-login now?"
        )
        if messagebox.askyesno("Authentication Required", prompt):
            try:
                self._audit("reauth_confirmed", account=account_name)
                name = self.account_manager.add_account()
                self.account_manager.load_account(name)
                self.account_label.config(text=f"Account: {name}")
                save_last_account(name)
                self.last_account_name = name
                self._audit("reauth_success", account=name)
                messagebox.showinfo("Success", f"Account re-authenticated: {name}")
            except Exception as err:
                self._audit("reauth_failed", level=logging.ERROR, account=account_name, error=str(err))
                messagebox.showerror("Error", str(err))
        else:
            self._audit("reauth_cancelled", account=account_name)

    def select_queue_row_by_index(self, index):
        try:
            list_pos = self.excel.df.index.get_loc(index)
        except KeyError:
            return
        self.queue_listbox.selection_clear(0, tk.END)
        self.queue_listbox.selection_set(list_pos)
        self.queue_listbox.activate(list_pos)
        self.queue_listbox.see(list_pos)

    def set_controls_for_running(self):
        self.start_button.config(state="disabled")
        self.pause_resume_button.config(state="normal", text="Pause")
        self.stop_button.config(state="normal")
        self.is_paused = False

    def set_controls_for_stopping(self):
        self.start_button.config(state="disabled")
        self.pause_resume_button.config(state="disabled")
        self.stop_button.config(state="disabled")

    def set_controls_for_idle(self):
        self.start_button.config(state="normal")
        self.pause_resume_button.config(state="disabled", text="Pause")
        self.stop_button.config(state="disabled")
        self.is_paused = False

    def is_file_locked_for_write(self, path):
        if not path or not os.path.exists(path):
            return False
        try:
            with open(path, "a+b"):
                return False
        except OSError:
            return True

    def warn_if_excel_open(self):
        excel_path = self.selected_excel_file
        if not self.is_file_locked_for_write(excel_path):
            return True

        proceed = messagebox.askyesno(
            "Excel File Open",
            "The Excel file appears to be open.\n"
            "Upload can continue, but status updates may not save until the file is closed.\n"
            "Do you want to continue?",
        )
        if proceed:
            self._audit("excel_open_continue", excel_file=excel_path)
        else:
            self._audit("excel_open_cancelled", level=logging.WARNING, excel_file=excel_path)
        return proceed

    def log(self, message):
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)


if __name__ == "__main__":
    root = tk.Tk()
    app = YouTubeUploadGUI(root)
    root.mainloop()
