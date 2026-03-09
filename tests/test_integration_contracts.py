from core.upload_worker import UploadWorker
from core import excel_manager as excel_mod
from core.youtube_service import YouTubeService


class DummyUploader:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls = []

    def start(self):
        self.calls.append("start")

    def stop(self):
        self.calls.append("stop")

    def pause(self):
        self.calls.append("pause")

    def resume(self):
        self.calls.append("resume")


class DummyInsertRequest:
    def __init__(self, *_args, **_kwargs):
        self.calls = 0

    def next_chunk(self):
        self.calls += 1
        if self.calls == 1:
            class Status:
                @staticmethod
                def progress():
                    return 0.5

            return Status(), None
        return None, {"id": "vid123"}


class DummyVideosApi:
    def __init__(self, parent):
        self.parent = parent

    def insert(self, part, body, media_body):
        self.parent.last_video_insert_body = body
        return DummyInsertRequest()


class DummyThumbApi:
    def __init__(self, parent):
        self.parent = parent

    def set(self, videoId, media_body):
        self.parent.last_thumb_video_id = videoId
        return self

    def execute(self):
        return {}


class DummyPlaylistApi:
    def __init__(self, parent):
        self.parent = parent

    def insert(self, part, body):
        self.parent.last_playlist_body = body
        return self

    def execute(self):
        return {}


class DummyYoutubeClient:
    def __init__(self, *_args, **_kwargs):
        self.last_video_insert_body = None
        self.last_thumb_video_id = None
        self.last_playlist_body = None

    def videos(self):
        return DummyVideosApi(self)

    def thumbnails(self):
        return DummyThumbApi(self)

    def playlistItems(self):
        return DummyPlaylistApi(self)


def test_upload_worker_proxies_controls(monkeypatch):
    holder = {}

    def fake_uploader_ctor(**kwargs):
        obj = DummyUploader(**kwargs)
        holder["obj"] = obj
        return obj

    monkeypatch.setattr("core.upload_worker.Uploader", fake_uploader_ctor)

    worker = UploadWorker(youtube_client="client", account_name="acc", progress_callback=lambda _: None)
    worker.run()
    worker.pause()
    worker.resume()
    worker.stop()

    assert holder["obj"].kwargs["account_name"] == "acc"
    assert holder["obj"].calls == [
        "start",
        "pause",
        "resume",
        "stop",
    ]


def test_youtube_service_injected_client_supports_publish_at(monkeypatch):
    dummy = DummyYoutubeClient()
    monkeypatch.setattr("core.youtube_service.MediaFileUpload", lambda *args, **kwargs: object())

    progress_values = []
    service = YouTubeService(dummy)
    video_id = service.upload_video(
        video_path="video.mp4",
        title="t",
        description="d",
        tags=["a"],
        privacy_status="private",
        category_id="22",
        publish_at="2026-01-01T00:00:00Z",
        progress_callback=progress_values.append,
    )

    assert video_id == "vid123"
    assert dummy.last_video_insert_body["status"]["publishAt"] == "2026-01-01T00:00:00Z"
    assert progress_values == [50]


def test_excel_manager_autosets_pending_and_ensures_columns(tmp_path, monkeypatch):
    excel_path = tmp_path / "data" / "upload_queue.xlsx"
    monkeypatch.setattr(excel_mod, "EXCEL_FILE", str(excel_path))

    manager = excel_mod.ExcelManager(videos_dir=str(tmp_path / "storage" / "videos"))
    manager.df.loc[0, "video_path"] = "a.mp4"
    manager.df.loc[0, "title"] = "A"
    manager.df.loc[0, "status"] = ""
    manager.save()

    reloaded = excel_mod.ExcelManager()
    assert "category_id" in reloaded.df.columns
    assert reloaded.df.loc[0, "status"] == "PENDING"


def test_uploader_stop_unblocks_when_paused(monkeypatch):
    class DummyExcel:
        def __init__(self, *_args, **_kwargs):
            pass

        def reset_uploading_rows(self):
            return None

    class DummyValidator:
        def __init__(self, *_args, **_kwargs):
            pass

    class DummyService:
        def __init__(self, *_args, **_kwargs):
            pass

    monkeypatch.setattr("core.uploader.ExcelManager", DummyExcel)
    monkeypatch.setattr("core.uploader.Validator", DummyValidator)
    monkeypatch.setattr("core.uploader.YouTubeService", DummyService)

    from core.uploader import Uploader

    uploader = Uploader(youtube_client="x")
    uploader.pause()
    assert not uploader.pause_event.is_set()

    uploader.stop()
    assert uploader.stop_event.is_set()
    assert uploader.pause_event.is_set()


def test_uploader_ignores_resume_index_when_state_account_differs(monkeypatch):
    class DummyExcel:
        def __init__(self, *_args, **_kwargs):
            import pandas as pd

            self.df = pd.DataFrame([{"status": "PENDING"}], index=[0])

        def reset_uploading_rows(self):
            return None

    class DummyValidator:
        def __init__(self, *_args, **_kwargs):
            pass

    class DummyService:
        def __init__(self, *_args, **_kwargs):
            pass

    monkeypatch.setattr("core.uploader.ExcelManager", DummyExcel)
    monkeypatch.setattr("core.uploader.Validator", DummyValidator)
    monkeypatch.setattr("core.uploader.YouTubeService", DummyService)

    from core.uploader import Uploader

    def fake_load_state(self):
        self.state = {"account_name": "other-account", "current_index": 0}

    monkeypatch.setattr(Uploader, "load_state", fake_load_state)

    uploader = Uploader(youtube_client="x", account_name="current-account")
    assert uploader._get_resume_index() is None


def test_uploader_ignores_terminal_resume_index(monkeypatch):
    class DummyExcel:
        def __init__(self, *_args, **_kwargs):
            import pandas as pd

            self.df = pd.DataFrame([{"status": "UPLOADED"}], index=[5])

        def reset_uploading_rows(self):
            return None

    class DummyValidator:
        def __init__(self, *_args, **_kwargs):
            pass

    class DummyService:
        def __init__(self, *_args, **_kwargs):
            pass

    monkeypatch.setattr("core.uploader.ExcelManager", DummyExcel)
    monkeypatch.setattr("core.uploader.Validator", DummyValidator)
    monkeypatch.setattr("core.uploader.YouTubeService", DummyService)

    from core.uploader import Uploader

    def fake_load_state(self):
        self.state = {"current_index": 5}

    monkeypatch.setattr(Uploader, "load_state", fake_load_state)

    uploader = Uploader(youtube_client="x")
    assert uploader._get_resume_index() is None


def test_excel_manager_duplicate_matches_relative_and_absolute_paths(tmp_path, monkeypatch):
    excel_path = tmp_path / "data" / "upload_queue.xlsx"
    monkeypatch.setattr(excel_mod, "EXCEL_FILE", str(excel_path))

    manager = excel_mod.ExcelManager(videos_dir=str(tmp_path / "storage" / "videos"))
    manager.df.loc[0, "video_path"] = "a.mp4"
    manager.df.loc[0, "status"] = "UPLOADED"
    manager.save()

    abs_path = tmp_path / "storage" / "videos" / "a.mp4"
    assert manager.is_duplicate(str(abs_path)) is True
    assert manager.is_duplicate("a.mp4") is True


def test_uploader_progress_callback_failure_does_not_crash(monkeypatch):
    class DummyExcel:
        def __init__(self, *_args, **_kwargs):
            import pandas as pd

            self.df = pd.DataFrame(
                [
                    {
                        "video_path": "storage/videos/a.mp4",
                        "thumbnail_path": "",
                        "title": "Title",
                        "description": "",
                        "tags": "",
                        "privacy_status": "private",
                        "schedule_time": "",
                        "playlist": "",
                        "category_id": "22",
                        "status": "PENDING",
                    }
                ],
                index=[0],
            )
            self.uploaded = False

        def reset_uploading_rows(self):
            return None

        def get_next_pending_index(self):
            pending = self.df[self.df["status"] == "PENDING"]
            if pending.empty:
                return None
            return pending.index[0]

        def is_duplicate(self, _video_path):
            return False

        def mark_uploading(self, index):
            self.df.at[index, "status"] = "UPLOADING"

        def mark_uploaded(self, index, _video_id):
            self.df.at[index, "status"] = "UPLOADED"
            self.uploaded = True

        def mark_failed(self, index, _error):
            self.df.at[index, "status"] = "FAILED"

    class DummyValidator:
        def __init__(self, *_args, **_kwargs):
            pass

        def validate_video(self, value):
            return value

        def validate_thumbnail(self, _value):
            return None

        def validate_title(self, value):
            return value

        def validate_description(self, value):
            return value

        def validate_tags(self, _value):
            return []

        def validate_privacy(self, value):
            return value

        def validate_schedule(self, _value):
            return None

    class DummyService:
        def __init__(self, *_args, **_kwargs):
            pass

        def upload_video(self, **kwargs):
            cb = kwargs["progress_callback"]
            cb(50)  # this will raise in user callback; uploader should swallow
            return "vid1"

        def upload_thumbnail(self, *_args, **_kwargs):
            return None

        def add_video_to_playlist(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr("core.uploader.ExcelManager", DummyExcel)
    monkeypatch.setattr("core.uploader.Validator", DummyValidator)
    monkeypatch.setattr("core.uploader.YouTubeService", DummyService)

    from core.uploader import Uploader

    def bad_progress(_value):
        raise RuntimeError("ui callback error")

    uploader = Uploader(youtube_client="x", progress_callback=bad_progress)
    uploader.start()

    assert uploader.excel.uploaded is True



def test_validator_uses_selected_source_folders_for_filename_only_rows(tmp_path):
    from core.validator import Validator
    from core.path_utils import normalize_path

    videos_dir = tmp_path / "videos"
    thumbs_dir = tmp_path / "thumbs"
    videos_dir.mkdir()
    thumbs_dir.mkdir()

    video_file = videos_dir / "sample.mp4"
    thumb_file = thumbs_dir / "sample.jpg"
    video_file.write_bytes(b"video")
    thumb_file.write_bytes(b"thumb")

    validator = Validator(videos_dir=str(videos_dir), thumbnails_dir=str(thumbs_dir))

    assert validator.validate_video("sample.mp4") == normalize_path(str(video_file))
    assert validator.validate_thumbnail("sample.jpg") == normalize_path(str(thumb_file))


def test_input_sources_persist_and_load(tmp_path, monkeypatch):
    from core import input_config

    file_path = tmp_path / "data" / "input_sources.json"
    monkeypatch.setattr(input_config, "INPUT_SOURCES_FILE", str(file_path))
    monkeypatch.setattr(input_config, "EXCEL_FILE", "default.xlsx")
    monkeypatch.setattr(input_config, "VIDEOS_DIR", "videos_default")
    monkeypatch.setattr(input_config, "THUMBNAILS_DIR", "thumbs_default")

    defaults = input_config.load_input_sources()
    assert defaults["excel_file"] == "default.xlsx"

    input_config.save_input_sources("queue.xlsx", "vdir", "tdir", "acc1")
    loaded = input_config.load_input_sources()
    assert loaded == {
        "excel_file": "queue.xlsx",
        "videos_dir": "vdir",
        "thumbnails_dir": "tdir",
        "last_account": "acc1",
    }


def test_input_sources_save_last_account_updates_only_account(tmp_path, monkeypatch):
    from core import input_config

    file_path = tmp_path / "data" / "input_sources.json"
    monkeypatch.setattr(input_config, "INPUT_SOURCES_FILE", str(file_path))
    monkeypatch.setattr(input_config, "EXCEL_FILE", "default.xlsx")
    monkeypatch.setattr(input_config, "VIDEOS_DIR", "videos_default")
    monkeypatch.setattr(input_config, "THUMBNAILS_DIR", "thumbs_default")

    input_config.save_input_sources("queue.xlsx", "vdir", "tdir", "")
    input_config.save_last_account("MyAccount")

    loaded = input_config.load_input_sources()
    assert loaded == {
        "excel_file": "queue.xlsx",
        "videos_dir": "vdir",
        "thumbnails_dir": "tdir",
        "last_account": "MyAccount",
    }


def test_uploader_real_file_path_smoke_flow(tmp_path, monkeypatch):
    from core.uploader import Uploader
    from core.excel_manager import ExcelManager
    from core.path_utils import normalize_path

    videos_dir = tmp_path / "videos"
    thumbs_dir = tmp_path / "thumbs"
    data_dir = tmp_path / "data"
    videos_dir.mkdir()
    thumbs_dir.mkdir()
    data_dir.mkdir()

    video_file = videos_dir / "sample.mp4"
    thumb_file = thumbs_dir / "sample.jpg"
    video_file.write_bytes(b"fake-video")
    thumb_file.write_bytes(b"fake-thumb")

    excel_file = data_dir / "upload_queue.xlsx"
    manager = ExcelManager(excel_file=str(excel_file), videos_dir=str(videos_dir))
    manager.df.loc[0, "video_path"] = "sample.mp4"
    manager.df.loc[0, "thumbnail_path"] = "sample.jpg"
    manager.df.loc[0, "title"] = "Smoke"
    manager.df.loc[0, "description"] = "Desc"
    manager.df.loc[0, "tags"] = "a,b"
    manager.df.loc[0, "playlist"] = "PL123"
    manager.df.loc[0, "category_id"] = "22"
    manager.df.loc[0, "privacy_status"] = "private"
    manager.df.loc[0, "schedule_time"] = ""
    manager.df.loc[0, "status"] = "PENDING"
    manager.save()

    class DummyService:
        def __init__(self, *_args, **_kwargs):
            self.uploaded = []
            self.thumbs = []
            self.playlists = []

        def upload_video(self, **kwargs):
            self.uploaded.append(kwargs)
            return "vid-smoke"

        def upload_thumbnail(self, video_id, thumbnail_path):
            self.thumbs.append((video_id, thumbnail_path))

        def add_video_to_playlist(self, video_id, playlist_id):
            self.playlists.append((video_id, playlist_id))

    monkeypatch.setattr("core.uploader.YouTubeService", DummyService)
    monkeypatch.setattr("core.uploader.APP_STATE_FILE", str(data_dir / "app_state.json"))

    uploader = Uploader(
        youtube_client="x",
        excel_file=str(excel_file),
        videos_dir=str(videos_dir),
        thumbnails_dir=str(thumbs_dir),
    )
    uploader.start()

    post = ExcelManager(excel_file=str(excel_file), videos_dir=str(videos_dir))
    assert post.df.loc[0, "status"] == "UPLOADED"
    assert post.df.loc[0, "video_id"] == "vid-smoke"
    assert post.df.loc[0, "youtube_url"] == "https://youtube.com/watch?v=vid-smoke"

    assert len(uploader.youtube_service.uploaded) == 1
    assert uploader.youtube_service.uploaded[0]["video_path"] == normalize_path(str(video_file))
    assert uploader.youtube_service.uploaded[0]["tags"] == ["a", "b"]
    assert uploader.youtube_service.uploaded[0]["category_id"] == "22"

    assert uploader.youtube_service.thumbs == [("vid-smoke", normalize_path(str(thumb_file)))]
    assert uploader.youtube_service.playlists == [("vid-smoke", "PL123")]


def test_excel_manager_reload_if_changed_detects_external_update(tmp_path):
    from core.excel_manager import ExcelManager

    excel_file = tmp_path / "data" / "upload_queue.xlsx"
    manager = ExcelManager(excel_file=str(excel_file), videos_dir=str(tmp_path / "videos"))

    # Initial check with no external change should be False
    assert manager.reload_if_changed() is False

    # External update through another manager instance should be detected
    writer = ExcelManager(excel_file=str(excel_file), videos_dir=str(tmp_path / "videos"))
    writer.df.loc[0, "video_path"] = "new.mp4"
    writer.df.loc[0, "status"] = "PENDING"
    writer.save()

    assert manager.reload_if_changed() is True
    assert manager.df.loc[0, "video_path"] == "new.mp4"


def test_path_utils_first_existing_and_normalize(tmp_path):
    from core.path_utils import first_existing_path, normalize_path

    existing = tmp_path / "x" / "a.txt"
    existing.parent.mkdir(parents=True)
    existing.write_text("ok", encoding="utf-8")

    result = first_existing_path(["/does/not/exist", str(existing)])
    assert result == normalize_path(str(existing))


def test_validator_resolve_path_prioritizes_selected_folder(tmp_path):
    from core.validator import Validator
    from core.path_utils import normalize_path

    base_dir = tmp_path / "base"
    selected = tmp_path / "selected"
    base_dir.mkdir()
    selected.mkdir()

    # same filename exists in both places, selected folder should win
    (base_dir / "same.mp4").write_bytes(b"base")
    (selected / "same.mp4").write_bytes(b"selected")

    import core.validator as validator_mod
    old_base = validator_mod.BASE_DIR
    validator_mod.BASE_DIR = str(base_dir)
    try:
        validator = Validator(videos_dir=str(selected), thumbnails_dir=str(selected))
        resolved = validator.resolve_path("same.mp4", str(selected))
        assert resolved == normalize_path(str((selected / "same.mp4").resolve()))
    finally:
        validator_mod.BASE_DIR = old_base


def test_uploader_classify_error_categories(monkeypatch):
    class DummyExcel:
        def __init__(self, *_args, **_kwargs):
            import pandas as pd

            self.df = pd.DataFrame([{"status": "PENDING"}], index=[0])

        def reset_uploading_rows(self):
            return None

    class DummyValidator:
        def __init__(self, *_args, **_kwargs):
            pass

    class DummyService:
        def __init__(self, *_args, **_kwargs):
            pass

    monkeypatch.setattr("core.uploader.ExcelManager", DummyExcel)
    monkeypatch.setattr("core.uploader.Validator", DummyValidator)
    monkeypatch.setattr("core.uploader.YouTubeService", DummyService)

    from core.uploader import Uploader

    uploader = Uploader(youtube_client="x")

    assert uploader._classify_error(FileNotFoundError("missing")) == "validation"
    assert uploader._classify_error(ValueError("bad value")) == "validation"
    assert uploader._classify_error(PermissionError("denied")) == "filesystem"
    assert uploader._classify_error(TimeoutError("timeout")) == "network"
    assert uploader._classify_error(ConnectionError("socket closed")) == "network"
    assert uploader._classify_error(RuntimeError("quota exceeded")) == "api_quota"
    assert uploader._classify_error(RuntimeError("token invalid")) == "authentication"
    assert uploader._classify_error(RuntimeError("api http error")) == "api"
    assert uploader._classify_error(RuntimeError("some unknown failure")) == "runtime"


def test_excel_manager_get_pending_rows_is_case_insensitive(tmp_path):
    from core.excel_manager import ExcelManager

    excel_file = tmp_path / "data" / "upload_queue.xlsx"
    manager = ExcelManager(excel_file=str(excel_file), videos_dir=str(tmp_path / "videos"))
    manager.df.loc[0, "video_path"] = "a.mp4"
    manager.df.loc[0, "status"] = " pending "
    manager.df.loc[1, "video_path"] = "b.mp4"
    manager.df.loc[1, "status"] = "FAILED"
    manager.save()

    pending = manager.get_pending_rows()
    assert len(pending) == 1
    assert pending.iloc[0]["video_path"] == "a.mp4"
