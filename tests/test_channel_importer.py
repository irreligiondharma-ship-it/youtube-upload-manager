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
