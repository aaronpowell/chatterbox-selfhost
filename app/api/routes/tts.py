import logging

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

        try:
            output_path = chatterbox_service.synthesize(
                payload.text,
                voice_prompt,
                exaggeration=payload.exaggeration,
                cfg_weight=payload.cfg_weight,
            )
        except Exception as exc:  # noqa: BLE001 - surface synthesis/model-load failures to the client
            logger.exception("Speech synthesis failed for voice_profile_id=%s", payload.voice_profile_id)
            raise HTTPException(status_code=500, detail=f"Speech synthesis failed: {exc}") from exc

        span.set_attribute("tts.output_path", output_path)
        return FileResponse(path=output_path, media_type="audio/wav", filename="speech.wav")


@router.post("/v1/audio/speech")
def openai_compatible_speech(payload: TTSRequest, session: Session = Depends(get_session)):
    return create_speech(payload, session)
