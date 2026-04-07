import pandas as pd
import pytest


def test_schedule_privacy_mismatch_helper():
    from gui.gui import YouTubeUploadGUI

    df = pd.DataFrame(
        [
            {"title": "A", "schedule_time": "2026-05-01 10:00", "privacy_status": "public"},
            {"title": "B", "schedule_time": "", "privacy_status": "private"},
            {"title": "C", "schedule_time": "2026-06-01 09:00", "privacy_status": "private"},
        ]
    )

    mismatches = YouTubeUploadGUI._find_schedule_privacy_mismatches(df)
    assert len(mismatches) == 1
    assert mismatches[0][0] == "A"


def test_channel_manager_controls_busy(monkeypatch):
    try:
        import tkinter as tk
        from tkinter import TclError
    except Exception:
        pytest.skip("tkinter not available")

    from gui import channel_manager_gui as cmg

    try:
        root = tk.Tk()
        root.withdraw()
    except TclError:
        pytest.skip("tkinter could not initialize")

    class DummyYoutube:
        pass

    monkeypatch.setattr(cmg.ChannelManagerGUI, "load_playlists_async", lambda self: None)

    gui = cmg.ChannelManagerGUI(root, youtube_client=DummyYoutube(), account_name="acc")
    try:
        gui.df = pd.DataFrame([{"title": "x"}])
        gui._set_controls_busy(True)
        assert str(gui.fetch_button["state"]) == "disabled"
        gui._set_controls_busy(False)
        assert str(gui.fetch_button["state"]) == "normal"
    finally:
        gui.dialog.destroy()
        root.destroy()
