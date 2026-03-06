import tkinter as tk
from tkinter import filedialog, ttk, messagebox
from PIL import Image, ImageTk
import os

from config.constants import APP_NAME, WINDOW_WIDTH, WINDOW_HEIGHT, BASE_DIR, EXCEL_FILE, VIDEOS_DIR, THUMBNAILS_DIR
from core.account_manager import AccountManager
from core.upload_worker import UploadWorker
from core.excel_manager import ExcelManager
from core.input_config import load_input_sources, save_input_sources, save_last_account
from config.settings import DELAY_SECONDS


class YouTubeUploadGUI:

    REFRESH_INTERVAL = 1000

    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.root.resizable(False, False)

        self.account_manager = AccountManager()
        self.upload_worker = None

        sources = load_input_sources()
        self.selected_excel_file = sources.get("excel_file", EXCEL_FILE)
        self.selected_videos_dir = sources.get("videos_dir", VIDEOS_DIR)
        self.selected_thumbnails_dir = sources.get("thumbnails_dir", THUMBNAILS_DIR)
        self.last_account_name = sources.get("last_account", "")

        self.excel = ExcelManager(excel_file=self.selected_excel_file, videos_dir=self.selected_videos_dir)

        self.thumbnail_image = None
        self.countdown_value = 0

        self.create_layout()
        self.load_accounts()
        self.refresh_queue()
        self.refresh_stats()

        self.root.after(self.REFRESH_INTERVAL, self.auto_refresh)

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

        self.delay_label = ttk.Label(status, text="Delay: Idle")
        self.delay_label.pack(anchor="w")

        self.progress = ttk.Progressbar(status, maximum=100)
        self.progress.pack(fill="x", pady=5)

        self.log_text = tk.Text(status, height=5)
        self.log_text.pack(fill="both", expand=True)

        bottom = ttk.Frame(self.root, padding=5)
        bottom.pack(fill="x")

        ttk.Button(bottom, text="Start",
                   command=self.start_upload).pack(side="left", padx=5)
        ttk.Button(bottom, text="Pause",
                   command=self.pause_upload).pack(side="left", padx=5)
        ttk.Button(bottom, text="Resume",
                   command=self.resume_upload).pack(side="left", padx=5)
        ttk.Button(bottom, text="Stop",
                   command=self.stop_upload).pack(side="left", padx=5)

        ttk.Button(bottom, text="Skip Current",
                   command=self.skip_current_delay).pack(side="right", padx=5)
        ttk.Button(bottom, text="Skip All",
                   command=self.skip_all_delay).pack(side="right", padx=5)
        ttk.Button(bottom, text="Restore Delay",
                   command=self.restore_delay).pack(side="right", padx=5)

    # ===============================
    # Account Handling
    # ===============================
    def load_accounts(self):
        accounts = sorted(self.account_manager.list_accounts())
        if accounts:
            target = self.last_account_name if self.last_account_name in accounts else accounts[0]
            self.account_manager.load_account(target)
            self.account_label.config(text=f"Account: {target}")

    def add_account(self):
        try:
            name = self.account_manager.add_account()
            self.account_manager.load_account(name)
            self.account_label.config(text=f"Account: {name}")
            save_last_account(name)
            self.last_account_name = name
            messagebox.showinfo("Success", f"Account added: {name}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def change_account(self):
        accounts = sorted(self.account_manager.list_accounts())
        if not accounts:
            messagebox.showwarning("No Accounts", "No accounts found.")
            return

        current = self.account_manager.get_current_account() or ""

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
            dialog.destroy()

        def on_select():
            choice = selected.get().strip()
            if not choice:
                messagebox.showerror("Invalid", "Please select an account.", parent=dialog)
                return

            if choice == current:
                dialog.destroy()
                messagebox.showinfo("Info", f"Already using account: {choice}")
                return

            try:
                self.account_manager.load_account(choice)
                self.account_label.config(text=f"Account: {choice}")
                save_last_account(choice)
                self.last_account_name = choice
                dialog.destroy()
                messagebox.showinfo("Success", f"Loaded account: {choice}")
            except Exception as err:
                messagebox.showerror("Error", str(err), parent=dialog)

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
            self.selected_excel_file = path
            self.apply_selected_sources()

    def select_videos_folder(self):
        path = filedialog.askdirectory(title="Select videos folder", initialdir=self.selected_videos_dir)
        if path:
            self.selected_videos_dir = path
            self.apply_selected_sources()

    def select_thumbnails_folder(self):
        path = filedialog.askdirectory(title="Select thumbnails folder", initialdir=self.selected_thumbnails_dir)
        if path:
            self.selected_thumbnails_dir = path
            self.apply_selected_sources()

    def validate_sources(self):
        issues = []

        if not os.path.isfile(self.selected_excel_file):
            issues.append(f"Excel file not found: {self.selected_excel_file}")
        if not os.path.isdir(self.selected_videos_dir):
            issues.append(f"Videos folder not found: {self.selected_videos_dir}")
        if not os.path.isdir(self.selected_thumbnails_dir):
            issues.append(f"Thumbnails folder not found: {self.selected_thumbnails_dir}")

        if issues:
            messagebox.showwarning("Input Sources Validation", "\n".join(issues))
        else:
            messagebox.showinfo("Input Sources Validation", "All selected input sources are valid.")

    def reset_sources_to_defaults(self):
        self.selected_excel_file = EXCEL_FILE
        self.selected_videos_dir = VIDEOS_DIR
        self.selected_thumbnails_dir = THUMBNAILS_DIR
        self.apply_selected_sources()

    # ===============================
    # Preview (Fixed)
    # ===============================
    def show_preview(self, event):
        selection = self.queue_listbox.curselection()
        if not selection:
            return

        index = selection[0]
        row = self.excel.df.iloc[index]

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
                img = Image.open(abs_path)
                img = img.resize((250, 140))
                self.thumbnail_image = ImageTk.PhotoImage(img)
                self.thumbnail_label.config(image=self.thumbnail_image)
            else:
                self.thumbnail_label.config(image="")
        else:
            self.thumbnail_label.config(image="")

    # ===============================
    # Upload Controls
    # ===============================
    def start_upload(self):
        if not self.account_manager.youtube:
            messagebox.showerror("Error", "No account loaded.")
            return

        self.upload_worker = UploadWorker(
            youtube_client=self.account_manager.youtube,
            account_name=self.account_manager.get_current_account(),
            progress_callback=self.update_progress,
            delay_callback=self.update_delay_from_uploader,
            excel_file=self.selected_excel_file,
            videos_dir=self.selected_videos_dir,
            thumbnails_dir=self.selected_thumbnails_dir
        )
        self.upload_worker.start()
        self.countdown_value = 0
        self.log("Upload started.")

    def pause_upload(self):
        if self.upload_worker:
            self.upload_worker.pause()
            self.log("Paused.")

    def resume_upload(self):
        if self.upload_worker:
            self.upload_worker.resume()
            self.log("Resumed.")

    def stop_upload(self):
        if self.upload_worker:
            self.upload_worker.stop()
            self.log("Stopped.")

    def skip_current_delay(self):
        if self.upload_worker:
            self.upload_worker.skip_current_delay()
            self.countdown_value = 0
            self.log("Skip current delay.")

    def skip_all_delay(self):
        if self.upload_worker:
            self.upload_worker.skip_all_delay()
            self.delay_label.config(text="Delay: Skipped (Session)")
            self.log("Skip all delays.")

    def restore_delay(self):
        if self.upload_worker:
            self.upload_worker.restore_delay()
            self.delay_label.config(text="Delay: Normal")
            self.log("Delay restored.")

    # ===============================
    # Auto Refresh
    # ===============================
    def auto_refresh(self):
        changed = self.excel.reload_if_changed()
        if changed:
            self.refresh_queue(reload=False)
            self.refresh_stats(reload=False)
        self.update_delay_display()
        self.root.after(self.REFRESH_INTERVAL, self.auto_refresh)

    def refresh_queue(self, reload=True):
        if reload:
            self.excel.reload()
        self.queue_listbox.delete(0, tk.END)
        for _, row in self.excel.df.iterrows():
            display = f"{row.get('title')} [{row.get('status')}]"
            self.queue_listbox.insert(tk.END, display)

    def refresh_stats(self, reload=True):
        if reload:
            self.excel.reload()
        stats = self.excel.get_stats()
        percent = 0
        if stats['total'] > 0:
            percent = int((stats['uploaded'] / stats['total']) * 100)

        self.progress["value"] = percent

        text = (
            f"Total: {stats['total']} | "
            f"Uploaded: {stats['uploaded']} | "
            f"Pending: {stats['pending']} | "
            f"Failed: {stats['failed']} | "
            f"Skipped: {stats['skipped']}"
        )
        self.stats_label.config(text=text)

    def update_delay_display(self):
        if self.countdown_value > 0:
            self.delay_label.config(text=f"Delay: {self.countdown_value} sec")

    def update_progress(self, value):
        # Called from worker thread; marshal UI update to Tk main thread
        self.root.after(0, lambda: self.progress.configure(value=value))

    def update_delay_from_uploader(self, remaining, mode):
        def _apply():
            if mode == "running" and remaining is not None:
                self.delay_label.config(text=f"Delay: {remaining} sec")
                self.countdown_value = int(remaining)
            elif mode == "finished":
                self.delay_label.config(text="Delay: Idle")
                self.countdown_value = 0
            elif mode == "skipped_session":
                self.delay_label.config(text="Delay: Skipped (Session)")
                self.countdown_value = 0
            elif mode == "skipped_current":
                self.delay_label.config(text="Delay: Skipped (Current)")
                self.countdown_value = 0

        self.root.after(0, _apply)

    def log(self, message):
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)


if __name__ == "__main__":
    root = tk.Tk()
    app = YouTubeUploadGUI(root)
    root.mainloop()