import io
import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from urllib.request import urlopen

import pandas as pd
from PIL import Image, ImageTk

from core.channel_manager import FULL_COLUMNS, ensure_columns, fetch_channel_videos


class _ScrollableFrame(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.vscroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vscroll.set)

        self.inner = ttk.Frame(self.canvas)
        self._window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.canvas.pack(side="left", fill="both", expand=True)
        self.vscroll.pack(side="right", fill="y")

        self.inner.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.inner.bind("<Enter>", self._bind_mousewheel)
        self.inner.bind("<Leave>", self._unbind_mousewheel)

    def _on_frame_configure(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self._window_id, width=event.width)

    def _bind_mousewheel(self, _event):
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind_all("<Button-4>", self._on_mousewheel)
        self.canvas.bind_all("<Button-5>", self._on_mousewheel)

    def _unbind_mousewheel(self, _event):
        self.canvas.unbind_all("<MouseWheel>")
        self.canvas.unbind_all("<Button-4>")
        self.canvas.unbind_all("<Button-5>")

    def _on_mousewheel(self, event):
        if getattr(event, "num", None) == 4:
            delta = -1
        elif getattr(event, "num", None) == 5:
            delta = 1
        else:
            delta = int(-1 * (event.delta / 120))
        self.canvas.yview_scroll(delta, "units")


class ChannelManagerGUI:
    def __init__(self, root, youtube_client, account_name=""):
        self.root = root
        self.youtube = youtube_client
        self.account_name = account_name or "Unknown"
        self.videos = []
        self._busy = False
        self.playlist_options = []
        self.playlist_by_display = {}
        self.playlist_id_to_display = {}
        self._playlist_combo = None
        self.selected_index = None
        self.scope_youtube = "https://www.googleapis.com/auth/youtube"
        self.scope_force_ssl = "https://www.googleapis.com/auth/youtube.force-ssl"
        self.scope_upload = "https://www.googleapis.com/auth/youtube.upload"
        self.scope_readonly = "https://www.googleapis.com/auth/youtube.readonly"

        self.dialog = tk.Toplevel(root)
        self.dialog.title("Channel Manager")
        self.dialog.transient(root)
        self.dialog.grab_set()
        self.dialog.geometry("980x620")
        self.dialog.resizable(True, True)

        header = ttk.Frame(self.dialog, padding=8)
        header.pack(fill="x")
        ttk.Label(header, text=f"Account: {self.account_name}").pack(side="left")

        controls = ttk.Frame(self.dialog, padding=8)
        controls.pack(fill="x")
        self.fetch_button = ttk.Button(controls, text="Fetch Channel Videos", command=self.fetch_videos)
        self.fetch_button.pack(side="left")
        self.load_button = ttk.Button(controls, text="Load Excel", command=self.load_excel)
        self.load_button.pack(side="left", padx=6)
        self.export_button = ttk.Button(controls, text="Export to Excel", command=self.export_excel, state="disabled")
        self.export_button.pack(side="left", padx=6)
        self.apply_selected_button = ttk.Button(
            controls, text="Apply Selected", command=self.apply_selected, state="disabled"
        )
        self.apply_selected_button.pack(side="left", padx=6)
        self.apply_all_button = ttk.Button(
            controls, text="Apply Pending", command=self.apply_pending, state="disabled"
        )
        self.apply_all_button.pack(side="left", padx=6)

        self.status_label = ttk.Label(self.dialog, text="Status: Idle")
        self.status_label.pack(anchor="w", padx=8)

        body = ttk.Frame(self.dialog, padding=8)
        body.pack(fill="both", expand=True)

        left = ttk.Frame(body)
        left.pack(side="left", fill="both", expand=True)

        self.listbox = tk.Listbox(left, exportselection=False)
        self.listbox.pack(fill="both", expand=True)
        self.listbox.bind("<<ListboxSelect>>", self.on_select)

        right = ttk.Frame(body)
        right.pack(side="right", fill="both", expand=True, padx=(8, 0))

        right_scroll = _ScrollableFrame(right)
        right_scroll.pack(fill="both", expand=True)

        preview = ttk.LabelFrame(right_scroll.inner, text="Preview", padding=6)
        preview.pack(fill="x")
        self.thumb_label = ttk.Label(preview)
        self.thumb_label.pack()
        self._thumb_image = None

        form = ttk.LabelFrame(right_scroll.inner, text="Edit Fields", padding=6)
        form.columnconfigure(1, weight=1)
        form.pack(fill="x", pady=(8, 0))

        self.field_vars = {}
        self._add_field(form, "title", 0)
        self._add_field(form, "description", 1, multiline=True)
        self._add_field(form, "tags", 2)
        self._add_dropdown_field(form, "privacy_status", 3, ["public", "private", "unlisted"])
        self._add_field(form, "category_id", 4)
        self._add_file_field(form, "thumbnail_path", 5)
        self._add_playlist_field(form, 6)
        self._add_field(form, "playlist_name", 7)
        self._add_action_field(form, 8)
        self._add_dropdown_field(form, "playlist_action", 9, ["", "add", "remove"])
        self._add_dropdown_field(form, "license", 10, ["youtube", "creativeCommon"])
        self._add_dropdown_field(form, "embeddable", 11, ["true", "false"])
        self._add_dropdown_field(form, "self_declared_made_for_kids", 12, ["true", "false"])
        self._add_field(form, "default_language", 13)
        self._add_field(form, "default_audio_language", 14)

        self.save_row_button = ttk.Button(form, text="Save Row (Excel)", command=self.save_row)
        self.save_row_button.grid(row=15, column=1, sticky="e", pady=(8, 0))

        bottom = ttk.Frame(self.dialog, padding=8)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="Close", command=self.dialog.destroy).pack(side="right")

        self.df = pd.DataFrame(columns=FULL_COLUMNS)
        self.excel_path = ""
        self.load_playlists_async()

    def set_status(self, text):
        self.status_label.config(text=text)

    def fetch_videos(self):
        if self._busy:
            return
        self._busy = True
        self.fetch_button.config(state="disabled")
        self.load_button.config(state="disabled")
        self.export_button.config(state="disabled")
        self.apply_selected_button.config(state="disabled")
        self.apply_all_button.config(state="disabled")
        self.listbox.delete(0, tk.END)
        self.set_status("Status: Fetching videos...")

        def run():
            try:
                videos = fetch_channel_videos(self.youtube, progress_callback=self.on_progress)
                self.df = pd.DataFrame(videos)
                ensure_columns(self.df)
                self.root.after(0, self.on_fetch_done)
            except Exception as err:
                self.root.after(0, lambda: self.on_fetch_error(err))

        threading.Thread(target=run, daemon=True).start()

    def on_progress(self, count):
        self.root.after(0, lambda: self.set_status(f"Status: Fetched {count} videos..."))

    def on_fetch_done(self):
        self.refresh_list()
        self.set_status(f"Status: Done. Total {len(self.df)} videos.")
        self.fetch_button.config(state="normal")
        self.load_button.config(state="normal")
        self.export_button.config(state="normal" if len(self.df) else "disabled")
        self.apply_selected_button.config(state="normal" if len(self.df) else "disabled")
        self.apply_all_button.config(state="normal" if len(self.df) else "disabled")
        self._busy = False
        self.load_playlists_async()

    def on_fetch_error(self, err):
        self.set_status("Status: Error")
        self.fetch_button.config(state="normal")
        self.load_button.config(state="normal")
        self.export_button.config(state="disabled")
        self.apply_selected_button.config(state="disabled")
        self.apply_all_button.config(state="disabled")
        self._busy = False
        messagebox.showerror("Error", str(err), parent=self.dialog)

    def export_excel(self):
        if self.df.empty:
            messagebox.showinfo("No Data", "No videos to export.", parent=self.dialog)
            return
        path = filedialog.asksaveasfilename(
            title="Save Channel Videos Excel",
            defaultextension=".xlsx",
            filetypes=[("Excel Files", "*.xlsx"), ("All Files", "*.*")],
        )
        if not path:
            return
        ensure_columns(self.df)
        self.df.to_excel(path, index=False)
        self.excel_path = path
        messagebox.showinfo("Exported", f"Saved {len(self.df)} videos to Excel.", parent=self.dialog)

    def load_excel(self):
        path = filedialog.askopenfilename(
            title="Open Channel Excel",
            filetypes=[("Excel Files", "*.xlsx *.xls"), ("All Files", "*.*")],
        )
        if not path:
            return
        df = pd.read_excel(path, dtype=str)
        self.df = ensure_columns(df.fillna(""))
        self.excel_path = path
        self.refresh_list()
        self.export_button.config(state="normal")
        self.apply_selected_button.config(state="normal")
        self.apply_all_button.config(state="normal")
        self.set_status(f"Status: Loaded {len(self.df)} rows.")
        self.load_playlists_async()

    def refresh_list(self):
        self.listbox.delete(0, tk.END)
        for _, row in self.df.iterrows():
            title = row.get("title", "")
            vid = row.get("video_id", "")
            status = row.get("status", "")
            prefix = f"[{status}] " if status else ""
            self.listbox.insert(tk.END, f"{prefix}{title} ({vid})")

    def on_select(self, _event):
        selection = self.listbox.curselection()
        if not selection:
            return
        index = selection[0]
        self.selected_index = index
        row = self.df.iloc[index]
        self._show_thumbnail(row)
        defaults = {
            "action": "update_all",
            "privacy_status": "private",
            "license": "youtube",
            "embeddable": "true",
            "self_declared_made_for_kids": "false",
        }
        for key in self.field_vars:
            value = str(row.get(key, "")).strip()
            if not value and key in defaults:
                value = defaults[key]
            if key == "playlist_id":
                value = self.playlist_id_to_display.get(value, value)
            if key == "playlist_name" and not value:
                mapped = self.playlist_by_display.get(self.field_vars.get("playlist_id", tk.StringVar()).get(), {})
                value = mapped.get("name", value)
            self.field_vars[key].set(value)

    def _show_thumbnail(self, row):
        thumb_path = str(row.get("thumbnail_path", "")).strip()
        thumb_url = str(row.get("thumbnail_url", "")).strip()
        img = None
        if thumb_path and os.path.exists(thumb_path):
            try:
                img = Image.open(thumb_path)
            except OSError:
                img = None
        elif thumb_url:
            try:
                with urlopen(thumb_url, timeout=5) as resp:
                    data = resp.read()
                img = Image.open(io.BytesIO(data))
            except Exception:
                img = None

        if img:
            img = img.resize((320, 180))
            self._thumb_image = ImageTk.PhotoImage(img)
            self.thumb_label.config(image=self._thumb_image)
        else:
            self.thumb_label.config(image="")

    def _add_field(self, parent, name, row, multiline=False):
        ttk.Label(parent, text=name).grid(row=row, column=0, sticky="w", pady=2)
        if multiline:
            text = tk.Text(parent, height=4)
            text.grid(row=row, column=1, sticky="we", pady=2)
            var = tk.StringVar()
            self.field_vars[name] = var

            def sync_from_var(*_):
                if text.get("1.0", tk.END).strip() != var.get():
                    text.delete("1.0", tk.END)
                    text.insert(tk.END, var.get())

            def sync_from_text(_event=None):
                var.set(text.get("1.0", tk.END).strip())

            var.trace_add("write", lambda *_: sync_from_var())
            text.bind("<KeyRelease>", sync_from_text)
        else:
            var = tk.StringVar()
            self.field_vars[name] = var
            entry = ttk.Entry(parent, textvariable=var)
            entry.grid(row=row, column=1, sticky="we", pady=2)

    def _add_action_field(self, parent, row):
        ttk.Label(parent, text="action").grid(row=row, column=0, sticky="w", pady=2)
        var = tk.StringVar()
        self.field_vars["action"] = var
        combo = ttk.Combobox(
            parent,
            textvariable=var,
            values=["update_all", "update_metadata", "update_thumbnail", "skip"],
            state="readonly",
        )
        combo.grid(row=row, column=1, sticky="we", pady=2)
        var.set("update_all")

    def _add_playlist_field(self, parent, row):
        ttk.Label(parent, text="playlist_id").grid(row=row, column=0, sticky="w", pady=2)
        var = tk.StringVar()
        self.field_vars["playlist_id"] = var
        combo = ttk.Combobox(parent, textvariable=var, values=self.playlist_options, state="normal")
        combo.grid(row=row, column=1, sticky="we", pady=2)
        combo.bind("<<ComboboxSelected>>", lambda _e: self._sync_playlist_name())
        self._playlist_combo = combo

    def _add_dropdown_field(self, parent, name, row, values):
        ttk.Label(parent, text=name).grid(row=row, column=0, sticky="w", pady=2)
        var = tk.StringVar()
        self.field_vars[name] = var
        combo = ttk.Combobox(
            parent,
            textvariable=var,
            values=values,
            state="readonly",
        )
        combo.grid(row=row, column=1, sticky="we", pady=2)

    def _add_file_field(self, parent, name, row):
        ttk.Label(parent, text=name).grid(row=row, column=0, sticky="w", pady=2)
        var = tk.StringVar()
        self.field_vars[name] = var
        entry = ttk.Entry(parent, textvariable=var)
        entry.grid(row=row, column=1, sticky="we", pady=2)

        def browse():
            path = filedialog.askopenfilename(
                title="Select Thumbnail",
                filetypes=[("Image Files", "*.jpg *.jpeg *.png"), ("All Files", "*.*")],
            )
            if path:
                var.set(path)

        ttk.Button(parent, text="Browse", command=browse).grid(row=row, column=2, padx=4)

    def _normalize_playlist_id(self, value: str) -> str:
        value = value.strip()
        info = self.playlist_by_display.get(value)
        if info:
            return info["id"]
        return value

    def _sync_playlist_name(self):
        display = self.field_vars.get("playlist_id", tk.StringVar()).get().strip()
        info = self.playlist_by_display.get(display)
        if info:
            self.field_vars.get("playlist_name", tk.StringVar()).set(info["name"])

    def load_playlists_async(self):
        if not self.youtube:
            return

        def run():
            try:
                playlists = []
                page_token = None
                while True:
                    resp = self.youtube.playlists().list(
                        part="snippet",
                        mine=True,
                        maxResults=50,
                        pageToken=page_token,
                    ).execute()
                    for item in resp.get("items", []):
                        pid = str(item.get("id", ""))
                        name = str(item.get("snippet", {}).get("title", ""))
                        if pid:
                            playlists.append((pid, name))
                    page_token = resp.get("nextPageToken")
                    if not page_token:
                        break
                self.root.after(0, lambda: self._set_playlists(playlists))
            except Exception:
                pass

        threading.Thread(target=run, daemon=True).start()

    def _set_playlists(self, playlists):
        self.playlist_options = []
        self.playlist_by_display = {}
        self.playlist_id_to_display = {}
        for pid, name in playlists:
            display = f"{name} | {pid}"
            self.playlist_options.append(display)
            self.playlist_by_display[display] = {"id": pid, "name": name}
            self.playlist_id_to_display[pid] = display
        if self._playlist_combo is not None:
            self._playlist_combo["values"] = self.playlist_options

    def save_row(self):
        selection = self.listbox.curselection()
        if selection:
            index = selection[0]
            self.selected_index = index
        elif self.selected_index is not None:
            index = self.selected_index
        else:
            messagebox.showinfo("No Selection", "Please select a row first.", parent=self.dialog)
            return
        playlist_raw = self.field_vars.get("playlist_id", tk.StringVar()).get().strip()
        playlist_id = self._normalize_playlist_id(playlist_raw)
        if playlist_id and playlist_raw in self.playlist_by_display:
            self.field_vars.get("playlist_name", tk.StringVar()).set(
                self.playlist_by_display[playlist_raw]["name"]
            )

        for key, var in self.field_vars.items():
            if key == "playlist_id":
                self.df.at[index, key] = playlist_id
            else:
                self.df.at[index, key] = var.get().strip()
        # mark as ready for update
        self.df.at[index, "status"] = "READY_TO_UPDATE"
        if self.excel_path:
            self.df.to_excel(self.excel_path, index=False)
        else:
            self.set_status("Status: Row saved in memory. Export to Excel to persist.")
        self.refresh_list()
        if self.excel_path:
            self.set_status("Status: Row saved to Excel.")
            messagebox.showinfo("Saved", "Row saved to Excel.", parent=self.dialog)
        else:
            messagebox.showinfo("Saved", "Row saved in memory. Export to Excel to persist.", parent=self.dialog)

    def apply_selected(self):
        selection = self.listbox.curselection()
        if not selection:
            return
        index = selection[0]
        ok, msg = self.apply_row(index)
        if ok:
            messagebox.showinfo("Success", msg, parent=self.dialog)
        else:
            messagebox.showerror("Failed", msg, parent=self.dialog)

    def apply_pending(self):
        total = 0
        success = 0
        failed = 0
        first_error = ""
        for idx, row in self.df.iterrows():
            if str(row.get("status", "")).upper() == "READY_TO_UPDATE":
                total += 1
                ok, msg = self.apply_row(idx)
                if ok:
                    success += 1
                else:
                    failed += 1
                    if not first_error:
                        first_error = msg
        if total == 0:
            messagebox.showinfo("Apply Pending", "No rows marked READY_TO_UPDATE.", parent=self.dialog)
        elif failed:
            messagebox.showerror(
                "Apply Pending",
                f"Completed with errors. Success: {success}, Failed: {failed}.\nFirst error: {first_error}",
                parent=self.dialog,
            )
        else:
            messagebox.showinfo("Apply Pending", f"All done. Success: {success}.", parent=self.dialog)

    def _get_scopes(self):
        creds = None
        if self.youtube is not None:
            http = getattr(self.youtube, "_http", None)
            if http is not None:
                creds = getattr(http, "credentials", None)
            if creds is None:
                creds = getattr(self.youtube, "credentials", None)
        scopes = getattr(creds, "scopes", None) or getattr(creds, "_scopes", None) or []
        return set(scopes)

    def _require_scopes(self, required_any, action_label):
        scopes = self._get_scopes()
        if not required_any:
            return ""
        if not scopes or not any(scope in scopes for scope in required_any):
            required_text = ", ".join(required_any)
            current_text = ", ".join(sorted(scopes)) if scopes else "unknown"
            return (
                f"Insufficient permission for {action_label}.\n"
                f"Required: {required_text}\n"
                f"Current: {current_text}\n"
                "Please re-login with required scopes."
            )
        return ""

    def apply_row(self, index):
        row = self.df.iloc[index]
        video_id = str(row.get("video_id", "")).strip()
        if not video_id:
            self.df.at[index, "status"] = "FAILED"
            self.df.at[index, "error_message"] = "Missing video_id"
            self.refresh_list()
            return False, "Missing video_id"

        action = str(row.get("action", "")).strip().lower()
        if action in ("skip", "ignored"):
            return True, f"Skipped {video_id}."

        try:
            playlist_action = str(row.get("playlist_action", "")).strip().lower()
            playlist_id = self._normalize_playlist_id(str(row.get("playlist_id", "")).strip())

            # update metadata
            if action in ("", "update", "update_metadata", "update_all"):
                msg = self._require_scopes([self.scope_youtube, self.scope_force_ssl], "metadata update")
                if msg:
                    raise PermissionError(msg)
                snippet = {
                    "title": str(row.get("title", "")),
                    "description": str(row.get("description", "")),
                    "categoryId": str(row.get("category_id", "")) or "22",
                }
                tags = str(row.get("tags", "")).strip()
                if tags:
                    snippet["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
                default_language = str(row.get("default_language", "")).strip()
                if default_language:
                    snippet["defaultLanguage"] = default_language
                default_audio = str(row.get("default_audio_language", "")).strip()
                if default_audio:
                    snippet["defaultAudioLanguage"] = default_audio

                status = {}
                privacy = str(row.get("privacy_status", "")).strip()
                if privacy:
                    status["privacyStatus"] = privacy
                license_value = str(row.get("license", "")).strip()
                if license_value:
                    status["license"] = license_value
                embeddable = str(row.get("embeddable", "")).strip()
                if embeddable:
                    status["embeddable"] = embeddable.lower() in ("true", "1", "yes")
                made_for_kids = str(row.get("self_declared_made_for_kids", "")).strip()
                if made_for_kids:
                    status["selfDeclaredMadeForKids"] = made_for_kids.lower() in ("true", "1", "yes")

                body = {"id": video_id, "snippet": snippet, "status": status}
                self.youtube.videos().update(part="snippet,status", body=body).execute()

            # update thumbnail
            thumb_path = str(row.get("thumbnail_path", "")).strip()
            if thumb_path and action in ("", "update", "update_thumbnail", "update_all"):
                msg = self._require_scopes(
                    [self.scope_upload, self.scope_youtube, self.scope_force_ssl],
                    "thumbnail update",
                )
                if msg:
                    raise PermissionError(msg)
                from googleapiclient.http import MediaFileUpload

                media = MediaFileUpload(thumb_path)
                self.youtube.thumbnails().set(videoId=video_id, media_body=media).execute()
            elif action in ("update_thumbnail",) and not thumb_path:
                raise ValueError("thumbnail_path is empty for update_thumbnail action.")

            # update playlist
            if playlist_action and playlist_id:
                msg = self._require_scopes([self.scope_youtube, self.scope_force_ssl], "playlist update")
                if msg:
                    raise PermissionError(msg)
                if playlist_action in ("add", "insert"):
                    body = {
                        "snippet": {
                            "playlistId": playlist_id,
                            "resourceId": {"kind": "youtube#video", "videoId": video_id},
                        }
                    }
                    self.youtube.playlistItems().insert(part="snippet", body=body).execute()
                elif playlist_action in ("remove", "delete"):
                    page_token = None
                    while True:
                        existing = self.youtube.playlistItems().list(
                            part="id,contentDetails",
                            playlistId=playlist_id,
                            maxResults=50,
                            pageToken=page_token,
                        ).execute()
                        for item in existing.get("items", []):
                            content = item.get("contentDetails", {})
                            if str(content.get("videoId", "")) == video_id:
                                item_id = item.get("id")
                                if item_id:
                                    self.youtube.playlistItems().delete(id=item_id).execute()
                        page_token = existing.get("nextPageToken")
                        if not page_token:
                            break
                else:
                    raise ValueError("Invalid playlist_action. Use add/remove.")
            elif playlist_action and not playlist_id:
                raise ValueError("playlist_id is required when playlist_action is set.")

            self.df.at[index, "status"] = "UPDATED"
            self.df.at[index, "error_message"] = ""
            success_msg = f"Updated {video_id}."
        except Exception as err:
            self.df.at[index, "status"] = "FAILED"
            self.df.at[index, "error_message"] = str(err)
            success_msg = str(err)
        if self.excel_path:
            self.df.to_excel(self.excel_path, index=False)
        self.refresh_list()
        return self.df.at[index, "status"] == "UPDATED", success_msg
