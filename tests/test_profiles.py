"""Tests for the voice profile API, including audio format validation."""

import io
import subprocess
import sys
import wave
from types import ModuleType
from unittest.mock import MagicMock, patch

def _make_wav_bytes() -> bytes:
    """Return minimal valid PCM WAV bytes."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(22050)
        wf.writeframes(b"\x00\x00" * 100)
    return buf.getvalue()


def _make_mp3_bytes() -> bytes:
    """Return bytes that look like an ID3-tagged MP3 (not readable by libsndfile)."""
    return b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x00" + b"\x00" * 100


def _soundfile_mock(raises: bool, side_effect=None) -> ModuleType:
    """Build a minimal soundfile stub that either succeeds or raises on info()."""
    sf = MagicMock()
    if side_effect is not None:
        sf.info.side_effect = side_effect
    elif raises:
        sf.info.side_effect = Exception("format not supported")
    return sf


class TestReferenceAudioValidation:
    """Upload endpoint should reject formats unsupported by libsndfile."""

    def test_wav_upload_accepted(self, client, tmp_path):
        sf_mock = _soundfile_mock(raises=False)
        with (
            patch("app.api.routes.profiles._SOUNDFILE_AVAILABLE", True),
            patch.dict(sys.modules, {"soundfile": sf_mock}),
        ):
            response = client.post(
                "/profiles",
                json={"name": "test-voice", "language": "en"},
            )
            assert response.status_code == 200
            profile_id = response.json()["id"]

            wav_bytes = _make_wav_bytes()
            response = client.post(
                f"/profiles/{profile_id}/reference-audio",
                files={"file": ("voice.wav", wav_bytes, "audio/wav")},
            )
            assert response.status_code == 200

    def test_mp3_upload_rejected(self, client, tmp_path):
        sf_mock = _soundfile_mock(raises=True)
        with (
            patch("app.api.routes.profiles._SOUNDFILE_AVAILABLE", True),
            patch.dict(sys.modules, {"soundfile": sf_mock}),
        ):
            response = client.post(
                "/profiles",
                json={"name": "test-voice-mp3", "language": "en"},
            )
            assert response.status_code == 200
            profile_id = response.json()["id"]

            response = client.post(
                f"/profiles/{profile_id}/reference-audio",
                files={"file": ("voice.mp3", _make_mp3_bytes(), "audio/mpeg")},
            )
            assert response.status_code == 422
            assert "ffmpeg" in response.json()["detail"]

    def test_m4a_upload_transcoded_to_wav(self, client, tmp_path):
        sf_mock = _soundfile_mock(raises=False, side_effect=[Exception("format not supported"), None])
        ffmpeg_result = subprocess.CompletedProcess(
            args=["ffmpeg"],
            returncode=0,
            stdout=_make_wav_bytes(),
            stderr=b"",
        )
        with (
            patch("app.api.routes.profiles._SOUNDFILE_AVAILABLE", True),
            patch.dict(sys.modules, {"soundfile": sf_mock}),
            patch("app.api.routes.profiles.subprocess.run", return_value=ffmpeg_result) as ffmpeg_run,
        ):
            response = client.post(
                "/profiles",
                json={"name": "test-voice-m4a", "language": "en"},
            )
            assert response.status_code == 200
            profile_id = response.json()["id"]

            response = client.post(
                f"/profiles/{profile_id}/reference-audio",
                files={"file": ("voice.m4a", b"fake-m4a-bytes", "audio/mp4")},
            )
            assert response.status_code == 200
            assert response.json()["reference_audio_path"].endswith("voice.wav")
            ffmpeg_run.assert_called_once()

    def test_upload_skips_validation_without_soundfile(self, client, tmp_path):
        """When soundfile is absent, uploads are accepted without format checks."""
        with patch("app.api.routes.profiles._SOUNDFILE_AVAILABLE", False):
            response = client.post(
                "/profiles",
                json={"name": "test-voice-nocheck", "language": "en"},
            )
            assert response.status_code == 200
            profile_id = response.json()["id"]

            response = client.post(
                f"/profiles/{profile_id}/reference-audio",
                files={"file": ("voice.mp3", _make_mp3_bytes(), "audio/mpeg")},
            )
            assert response.status_code == 200
