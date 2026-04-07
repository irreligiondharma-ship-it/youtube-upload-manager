import pytest


def test_sanitize_filename_handles_invalid_chars():
    from core.channel_importer import sanitize_filename

    value = 'A<>:"/\\|?*B'
    result = sanitize_filename(value)
    assert "<" not in result
    assert ">" not in result
    assert result.lower().startswith("a")


def test_resolve_channel_id_direct_id_skips_api():
    from core.channel_importer import resolve_channel_id

    class DummyYoutube:
        def channels(self):
            raise AssertionError("channels() should not be called")

        def search(self):
            raise AssertionError("search() should not be called")

    direct = "UC1234567890123456789012"
    assert resolve_channel_id(DummyYoutube(), direct) == direct


def test_resolve_channel_id_handle_uses_channels_list():
    from core.channel_importer import resolve_channel_id

    class DummyChannels:
        def __init__(self):
            self.kwargs = None

        def list(self, **kwargs):
            self.kwargs = kwargs
            return self

        def execute(self):
            return {"items": [{"id": "UC999"}]}

    class DummyYoutube:
        def __init__(self):
            self._channels = DummyChannels()

        def channels(self):
            return self._channels

        def search(self):
            raise AssertionError("search() should not be called")

    dummy = DummyYoutube()
    assert resolve_channel_id(dummy, "@testhandle") == "UC999"
    assert "forHandle" in dummy._channels.kwargs


def test_extract_video_id_from_url():
    from core.channel_importer import extract_video_id

    vid = "dQw4w9WgXcQ"
    assert extract_video_id(f"https://youtu.be/{vid}") == vid
    assert extract_video_id(f"https://www.youtube.com/watch?v={vid}") == vid
    assert extract_video_id(vid) == vid


def test_find_existing_video_file(tmp_path):
    from core.channel_importer import find_existing_video_file

    vid = "dQw4w9WgXcQ"
    folder = tmp_path / "videos"
    folder.mkdir()
    path = folder / f"Sample [{vid}].mp4"
    path.write_bytes(b"data")

    found = find_existing_video_file(str(folder), vid)
    assert found is not None
    assert found.lower().endswith(".mp4")
