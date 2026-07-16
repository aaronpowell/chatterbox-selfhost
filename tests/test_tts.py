import io
import wave
from unittest.mock import patch

from app.models import VoiceProfile


def _empty_wav_file(path):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(22050)
        wf.writeframes(b"")
    path.write_bytes(buffer.getvalue())


def test_create_speech_includes_generation_timing_header(client, tmp_path):
    output_file = tmp_path / "speech.wav"
    output_file.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")

    with (
        patch("app.api.routes.tts.chatterbox_service._available", True),
        patch("app.api.routes.tts.chatterbox_service.synthesize", return_value=str(output_file)) as synthesize,
    ):
        response = client.post("/audio/speech", json={"text": "hello world"})

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert "x-generation-time-ms" in response.headers
    assert int(response.headers["x-generation-time-ms"]) >= 0
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
