"""Tests for the voice profile API, including audio format validation."""

import io
from pathlib import Path
import shutil
import subprocess
import sys
import wave
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def isolate_profile_storage(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def _make_wav_bytes() -> bytes:
    """Return minimal valid PCM WAV bytes."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(22050)
        wf.writeframes(b"\x00\x00" * 100)
    return buf.getvalue()


def _make_empty_wav_bytes() -> bytes:
    """Return a WAV header with zero audio frames."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(22050)
        wf.writeframes(b"")
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
    else:
        sf.info.return_value = MagicMock(frames=100)
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
        sf_mock = _soundfile_mock(raises=False, side_effect=[Exception("format not supported"), MagicMock(frames=100)])
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

    def test_upload_rejects_unverifiable_format_without_soundfile(self, client, tmp_path):
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
            assert response.status_code == 422

    def test_empty_wav_upload_rejected(self, client, tmp_path):
        sf_mock = _soundfile_mock(raises=False)
        sf_mock.info.return_value = MagicMock(frames=0)
        with (
            patch("app.api.routes.profiles._SOUNDFILE_AVAILABLE", True),
            patch.dict(sys.modules, {"soundfile": sf_mock}),
        ):
            response = client.post(
                "/profiles",
                json={"name": "test-voice-empty", "language": "en"},
            )
            assert response.status_code == 200
            profile_id = response.json()["id"]

            response = client.post(
                f"/profiles/{profile_id}/reference-audio",
                files={"file": ("voice.wav", _make_empty_wav_bytes(), "audio/wav")},
            )
            assert response.status_code == 422
            assert "empty" in response.json()["detail"].lower()

    def test_delete_profile_removes_profile_and_audio(self, client, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch("app.api.routes.profiles._SOUNDFILE_AVAILABLE", False):
            create_response = client.post(
                "/profiles",
                json={"name": "to-delete", "language": "en"},
            )
            assert create_response.status_code == 200
            profile_id = create_response.json()["id"]

            upload_response = client.post(
                f"/profiles/{profile_id}/reference-audio",
                files={"file": ("voice.wav", _make_wav_bytes(), "audio/wav")},
            )
            assert upload_response.status_code == 200
            reference_audio_path = Path(upload_response.json()["reference_audio_path"])
            assert reference_audio_path.exists()

            delete_response = client.delete(f"/profiles/{profile_id}")
            assert delete_response.status_code == 200
            assert delete_response.json() == {"status": "deleted", "profile_id": profile_id}

            profiles_response = client.get("/profiles")
            assert profiles_response.status_code == 200
            assert all(profile["id"] != profile_id for profile in profiles_response.json())
            assert not reference_audio_path.exists()
            assert not (Path("audio") / "profiles" / str(profile_id)).exists()

    def test_delete_profile_returns_404_when_missing(self, client):
        response = client.delete("/profiles/999")
        assert response.status_code == 404
        assert response.json()["detail"] == "Profile not found."

    @pytest.mark.parametrize("with_soundfile", [True, False])
    def test_empty_upload_rejected_without_writing_files(self, client, with_soundfile):
        profile_id = client.post("/profiles", json={"name": "empty-upload"}).json()["id"]
        with patch("app.api.routes.profiles._SOUNDFILE_AVAILABLE", with_soundfile):
            response = client.post(
                f"/profiles/{profile_id}/reference-audio",
                files={"file": ("voice.wav", b"", "audio/wav")},
            )
        assert response.status_code == 422
        assert not (Path("audio") / "profiles" / str(profile_id)).exists()

    def test_empty_wav_rejected_without_soundfile(self, client):
        profile_id = client.post("/profiles", json={"name": "empty-wav"}).json()["id"]
        with patch("app.api.routes.profiles._SOUNDFILE_AVAILABLE", False):
            response = client.post(
                f"/profiles/{profile_id}/reference-audio",
                files={"file": ("voice.wav", _make_empty_wav_bytes(), "audio/wav")},
            )
        assert response.status_code == 422

    def test_upload_filename_cannot_escape_profile_directory(self, client):
        profile_id = client.post("/profiles", json={"name": "safe-upload"}).json()["id"]
        with patch("app.api.routes.profiles._SOUNDFILE_AVAILABLE", False):
            response = client.post(
                f"/profiles/{profile_id}/reference-audio",
                files={"file": ("..\\..\\escaped.wav", _make_wav_bytes(), "audio/wav")},
            )
        assert response.status_code == 200
        assert Path(response.json()["reference_audio_path"]) == Path("audio") / "profiles" / str(profile_id) / "escaped.wav"

    def test_delete_does_not_remove_external_reference_file(self, client, db_session, tmp_path):
        from app.models import VoiceProfile

        external = tmp_path / "shared.wav"
        external.write_bytes(_make_wav_bytes())
        profile = VoiceProfile(name="external-reference", reference_audio_path=str(external))
        db_session.add(profile)
        db_session.commit()
        db_session.refresh(profile)
        assert client.delete(f"/profiles/{profile.id}").status_code == 200
        assert external.exists()

    def test_delete_without_audio_allows_name_reuse(self, client):
        profile_id = client.post("/profiles", json={"name": "reusable"}).json()["id"]
        assert client.delete(f"/profiles/{profile_id}").status_code == 200
        assert client.delete(f"/profiles/{profile_id}").status_code == 404
        assert client.post("/profiles", json={"name": "reusable"}).status_code == 200

    def test_delete_failure_keeps_profile(self, client):
        profile_id = client.post("/profiles", json={"name": "keep-on-error"}).json()["id"]
        audio_dir = Path("audio") / "profiles" / str(profile_id)
        audio_dir.mkdir(parents=True)
        with patch("app.api.routes.profiles.shutil.rmtree", side_effect=PermissionError("locked")):
            response = client.delete(f"/profiles/{profile_id}")
        assert response.status_code == 500
        assert any(profile["id"] == profile_id for profile in client.get("/profiles").json())

    def test_delete_removes_only_owned_audio_directory(self, client):
        profile_id = client.post("/profiles", json={"name": "owned-audio"}).json()["id"]
        owned = Path("audio") / "profiles" / str(profile_id)
        owned.mkdir(parents=True)
        (owned / "old-reference.wav").write_bytes(_make_wav_bytes())
        neighbour = Path("audio") / "profiles" / str(profile_id + 1)
        neighbour.mkdir()
        other_file = neighbour / "other.wav"
        other_file.write_bytes(_make_wav_bytes())
        assert client.delete(f"/profiles/{profile_id}").status_code == 200
        assert not owned.exists()
        assert other_file.exists()

    def test_delete_refuses_linked_audio_directory(self, client):
        profile_id = client.post("/profiles", json={"name": "linked-audio"}).json()["id"]
        with patch("app.api.routes.profiles.Path.is_symlink", return_value=True):
            response = client.delete(f"/profiles/{profile_id}")
        assert response.status_code == 409
        assert any(profile["id"] == profile_id for profile in client.get("/profiles").json())


def test_create_profile_with_audio_is_ready(client):
    with patch("app.api.routes.profiles._SOUNDFILE_AVAILABLE", False):
        response = client.post(
            "/profiles/with-audio",
            data={"name": "complete", "language": "en"},
            files={"file": ("voice.wav", _make_wav_bytes(), "audio/wav")},
        )
    assert response.status_code == 200
    assert Path(response.json()["reference_audio_path"]).read_bytes() == _make_wav_bytes()
    assert client.get("/profiles").json()[0]["audio_ready"] is True


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
def test_create_profile_transcodes_m4a_with_ffmpeg(client, tmp_path):
    source = tmp_path / "source.wav"
    encoded = tmp_path / "source.m4a"
    source.write_bytes(_make_wav_bytes())
    subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(source), str(encoded)],
        check=True,
        capture_output=True,
    )
    with patch("app.api.routes.profiles._SOUNDFILE_AVAILABLE", False):
        response = client.post(
            "/profiles/with-audio",
            data={"name": "m4a-voice"},
            files={"file": ("voice.m4a", encoded.read_bytes(), "audio/mp4")},
        )
    assert response.status_code == 200
    with wave.open(response.json()["reference_audio_path"], "rb") as wav:
        assert wav.readframes(1)


@pytest.mark.parametrize("content", [b"", b"not audio"])
def test_create_profile_with_bad_audio_does_not_save_profile(client, content):
    with patch("app.api.routes.profiles._SOUNDFILE_AVAILABLE", False):
        response = client.post(
            "/profiles/with-audio",
            data={"name": "invalid"},
            files={"file": ("voice.wav", content, "audio/wav")},
        )
    assert response.status_code == 422
    assert client.get("/profiles").json() == []
    assert not Path("audio").exists()


def test_create_profile_storage_failure_rolls_back(client):
    with (
        patch("app.api.routes.profiles._SOUNDFILE_AVAILABLE", False),
        patch("app.api.routes.profiles.Path.write_bytes", side_effect=PermissionError("read-only")),
        pytest.raises(PermissionError),
    ):
        client.post(
            "/profiles/with-audio",
            data={"name": "storage-failure"},
            files={"file": ("voice.wav", _make_wav_bytes(), "audio/wav")},
        )
    assert client.get("/profiles").json() == []
    assert not (Path("audio") / "profiles" / "1").exists()


def test_create_profile_preserves_existing_directory_on_collision(client):
    existing = Path("audio") / "profiles" / "1"
    existing.mkdir(parents=True)
    original = existing / "original.wav"
    original.write_bytes(b"existing")
    with (
        patch("app.api.routes.profiles._SOUNDFILE_AVAILABLE", False),
        pytest.raises(FileExistsError),
    ):
        client.post(
            "/profiles/with-audio",
            data={"name": "collision"},
            files={"file": ("voice.wav", _make_wav_bytes(), "audio/wav")},
        )
    assert original.read_bytes() == b"existing"
    assert client.get("/profiles").json() == []


def test_profile_list_marks_missing_audio_not_ready(client):
    client.post("/profiles", json={"name": "incomplete"})
    assert client.get("/profiles").json()[0]["audio_ready"] is False
