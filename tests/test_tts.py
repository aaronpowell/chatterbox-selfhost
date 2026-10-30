import io
import logging
import wave
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from app.models import VoiceProfile
from app.services.chatterbox_service import chatterbox_service


def _empty_wav_file(path):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(22050)
        wf.writeframes(b"")
    path.write_bytes(buffer.getvalue())


@pytest.mark.parametrize("endpoint", ["/audio/speech", "/audio/v1/audio/speech"])
def test_create_speech_includes_generation_timing_header(client, tmp_path, endpoint):
    output_file = tmp_path / "speech.wav"
    output_file.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")

    with (
        patch("app.api.routes.tts.chatterbox_service._available", True),
        patch("app.api.routes.tts.chatterbox_service.synthesize", return_value=str(output_file)) as synthesize,
        patch("app.api.routes.tts.time", SimpleNamespace(perf_counter=Mock(side_effect=[10.0, 12.5]))),
    ):
        response = client.post(endpoint, json={"text": "hello world"})

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert "x-generation-time-ms" in response.headers
    assert response.headers["x-generation-time-ms"] == "2500"
    synthesize.assert_called_once()


def test_openai_compatible_speech_includes_generation_timing_header(client, tmp_path):
    output_file = tmp_path / "speech.wav"
    output_file.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")

    with (
        patch("app.api.routes.tts.chatterbox_service._available", True),
        patch("app.api.routes.tts.chatterbox_service.synthesize", return_value=str(output_file)),
    ):
        response = client.post("/audio/v1/audio/speech", json={"text": "hello world"})

    assert response.status_code == 200
    assert "x-generation-time-ms" in response.headers


def test_create_speech_rejects_empty_voice_prompt(client, db_session, tmp_path):
    empty_prompt = tmp_path / "empty.wav"
    _empty_wav_file(empty_prompt)

    profile = VoiceProfile(name="empty-profile", language="en", reference_audio_path=str(empty_prompt))
    db_session.add(profile)
    db_session.commit()
    db_session.refresh(profile)

    with patch("app.api.routes.tts.chatterbox_service._available", True):
        response = client.post(
            "/audio/speech",
            json={"text": "hello world", "voice_profile_id": profile.id},
        )

    assert response.status_code == 422
    assert "empty" in response.json()["detail"].lower()


def test_invalid_wav_prompt_without_soundfile_returns_422(client, db_session, tmp_path):
    prompt = tmp_path / "invalid.wav"
    prompt.write_bytes(b"RIFF")
    profile = VoiceProfile(name="invalid-prompt", reference_audio_path=str(prompt))
    db_session.add(profile)
    db_session.commit()
    with (
        patch.object(chatterbox_service, "_available", True),
        patch("app.api.routes.tts._SOUNDFILE_AVAILABLE", False),
        patch.object(chatterbox_service, "synthesize") as synthesize,
    ):
        response = client.post("/audio/speech", json={"text": "hello", "voice_profile_id": profile.id})
    assert response.status_code == 422
    synthesize.assert_not_called()


@pytest.mark.parametrize(
    ("stage", "error"),
    [
        ("import_audio_backend", ImportError("Audio backend unavailable")),
        ("load_model", RuntimeError("Model load failed")),
        ("generate_audio", FileNotFoundError("Reference audio missing")),
        ("save_audio", OSError("Audio storage is read-only")),
    ],
)
@pytest.mark.parametrize("endpoint", ["/audio/speech", "/audio/v1/audio/speech"])
def test_synthesis_failure_logs_context_and_traceback(client, db_session, tmp_path, caplog, stage, error, endpoint):
    prompt = tmp_path / "reference.wav"
    with wave.open(str(prompt), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22050)
        wav_file.writeframes(b"\x00\x00" * 100)
    profile = VoiceProfile(name="test-voice", reference_audio_path=str(prompt))
    db_session.add(profile)
    db_session.commit()
    db_session.refresh(profile)
    text = "Private text that must not appear in diagnostic fields."
    model = SimpleNamespace(generate=Mock(return_value=object()), sr=24000)
    audio_backend = SimpleNamespace(save=Mock())
    if stage == "generate_audio":
        model.generate.side_effect = error
    elif stage == "save_audio":
        audio_backend.save.side_effect = error

    with (
        caplog.at_level(logging.ERROR),
        patch.object(chatterbox_service, "_available", True),
        patch.object(chatterbox_service, "_model_device", "cpu"),
        patch.object(
            chatterbox_service, "_ensure_model",
            side_effect=error if stage == "load_model" else None,
            return_value=model,
        ),
        patch.dict("sys.modules", {"torchaudio": None if stage == "import_audio_backend" else audio_backend}),
    ):
        response = client.post(
            endpoint,
            json={"text": text, "voice_profile_id": profile.id},
            headers={"X-Request-ID": "speech-failure-test"},
        )

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "speech-failure-test"
    service_record = next(
        record for record in caplog.records if record.name == "app.services.chatterbox_service"
    )
    assert f"stage={stage}" in service_record.getMessage()
    assert "device=cpu" in service_record.getMessage()
    assert f"reference_audio={prompt}" in service_record.getMessage()
    assert f"text_length={len(text)}" in service_record.getMessage()
    assert "output_path=" in service_record.getMessage()
    api_record = next(record for record in caplog.records if record.name == "app.api.routes.tts")
    assert f"voice_profile_id={profile.id}" in api_record.getMessage()
    assert service_record.request_id == api_record.request_id == "speech-failure-test"
    assert api_record.exc_info is not None
    if stage != "import_audio_backend":
        assert api_record.exc_info[1] is error
    assert "Traceback (most recent call last)" in caplog.text
    assert text not in caplog.text


def test_synthesis_success_logs_progress_and_returns_audio(client, tmp_path, caplog):
    from app.config import settings

    text = "Private speech content."
    wav = object()
    model = SimpleNamespace(generate=Mock(return_value=wav), sr=24000)
    output_path = tmp_path / "latest.wav"
    audio_bytes = b"test-audio"
    audio_backend = SimpleNamespace(
        save=Mock(side_effect=lambda path, audio, sr: output_path.write_bytes(audio_bytes)),
    )

    with (
        caplog.at_level(logging.INFO),
        patch.object(settings, "audio_storage_path", str(tmp_path)),
        patch.object(chatterbox_service, "_available", True),
        patch.object(chatterbox_service, "_model_device", "cpu"),
        patch.object(chatterbox_service, "_ensure_model", return_value=model),
        patch.dict("sys.modules", {"torchaudio": audio_backend}),
    ):
        response = client.post("/audio/speech", json={"text": text})

    assert response.status_code == 200
    assert response.content == audio_bytes
    assert response.headers["content-type"] == "audio/wav"
    model.generate.assert_called_once_with(
        text, audio_prompt_path=None, exaggeration=0.5, cfg_weight=0.5,
    )
    audio_backend.save.assert_called_once_with(str(output_path), wav, model.sr)
    for stage in ("load_model", "generate_audio", "save_audio"):
        assert f"stage={stage}" in caplog.text
    assert not any(record.levelno >= logging.ERROR for record in caplog.records)
    assert text not in caplog.text
