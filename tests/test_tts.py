import logging
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from app.models import VoiceProfile
from app.services.chatterbox_service import chatterbox_service


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
def test_synthesis_failure_logs_context_and_traceback(client, db_session, caplog, stage, error, endpoint):
    profile = VoiceProfile(name="test-voice", reference_audio_path="missing-reference.wav")
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
    assert "reference_audio=missing-reference.wav" in service_record.getMessage()
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
