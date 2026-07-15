from types import SimpleNamespace
from unittest.mock import patch

from app.config import settings
from app.services.chatterbox_service import _resolve_tts_device


def test_resolve_tts_device_cpu_mode():
    with patch.object(settings, "tts_device", "cpu"):
        assert _resolve_tts_device() == "cpu"


def test_resolve_tts_device_auto_uses_cuda_when_available():
    fake_torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True))
    with (
        patch.object(settings, "tts_device", "auto"),
        patch.dict("sys.modules", {"torch": fake_torch}),
    ):
        assert _resolve_tts_device() == "cuda"


def test_resolve_tts_device_auto_falls_back_to_cpu_without_torch():
    with (
        patch.object(settings, "tts_device", "auto"),
        patch.dict("sys.modules", {"torch": None}),
    ):
        assert _resolve_tts_device() == "cpu"


def test_resolve_tts_device_cuda_falls_back_when_unavailable():
    fake_torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False))
    with (
        patch.object(settings, "tts_device", "cuda"),
        patch.dict("sys.modules", {"torch": fake_torch}),
    ):
        assert _resolve_tts_device() == "cpu"
