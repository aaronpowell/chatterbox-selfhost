import logging
import time
from pathlib import Path
import importlib.util

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlmodel import Session

from app.db import get_session
from app.models import VoiceProfile
from app.observability import get_tracer
from app.schemas import TTSRequest
from app.services.chatterbox_service import chatterbox_service

router = APIRouter(prefix="/audio", tags=["tts"])
logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)
_SOUNDFILE_AVAILABLE = importlib.util.find_spec("soundfile") is not None


def _validate_voice_prompt(path: str) -> None:
    prompt_path = Path(path)
    if not prompt_path.exists():
        raise HTTPException(status_code=422, detail="Voice profile reference audio file is missing.")

    if not _SOUNDFILE_AVAILABLE:
        return

    import soundfile as sf  # type: ignore

    try:
        info = sf.info(str(prompt_path))
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail="Voice profile reference audio could not be read. Upload a valid WAV/FLAC/OGG clip.",
        ) from exc
    if info.frames <= 0:
        raise HTTPException(status_code=422, detail="Voice profile reference audio is empty. Upload a non-empty clip.")


@router.post("/speech")
def create_speech(payload: TTSRequest, session: Session = Depends(get_session)):
    with tracer.start_as_current_span("tts.create_speech") as span:
        span.set_attribute("tts.text.length", len(payload.text))
        span.set_attribute("tts.voice_profile_id", payload.voice_profile_id or 0)
        span.set_attribute("tts.output_format", payload.format)

        if not chatterbox_service.is_available:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Speech model is not available. The Chatterbox TTS model isn't "
                    "installed in this environment. Install it with "
                    "'uv sync --extra tts' on Python 3.11/3.12 to enable synthesis."
                ),
            )

        voice_prompt = None
        if payload.voice_profile_id:
            profile = session.get(VoiceProfile, payload.voice_profile_id)
            if not profile:
                raise HTTPException(status_code=404, detail="Voice profile not found.")
            voice_prompt = profile.reference_audio_path or None
            if voice_prompt:
                _validate_voice_prompt(voice_prompt)

        try:
            synthesis_started = time.perf_counter()
            output_path = chatterbox_service.synthesize(
                payload.text,
                voice_prompt,
                exaggeration=payload.exaggeration,
                cfg_weight=payload.cfg_weight,
            )
            generation_time_ms = int((time.perf_counter() - synthesis_started) * 1000)
        except Exception as exc:  # noqa: BLE001 - surface synthesis/model-load failures to the client
            logger.exception("Speech synthesis failed for voice_profile_id=%s", payload.voice_profile_id)
            raise HTTPException(status_code=500, detail=f"Speech synthesis failed: {exc}") from exc

        span.set_attribute("tts.output_path", output_path)
        span.set_attribute("tts.generation_time_ms", generation_time_ms)
        return FileResponse(
            path=output_path,
            media_type="audio/wav",
            filename="speech.wav",
            headers={"X-Generation-Time-Ms": str(generation_time_ms)},
        )


@router.post("/v1/audio/speech")
def openai_compatible_speech(payload: TTSRequest, session: Session = Depends(get_session)):
    return create_speech(payload, session)
