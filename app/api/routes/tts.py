from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlmodel import Session

from app.db import get_session
from app.models import VoiceProfile
from app.schemas import TTSRequest
from app.services.chatterbox_service import chatterbox_service

router = APIRouter(prefix="/audio", tags=["tts"])


@router.post("/speech")
def create_speech(payload: TTSRequest, session: Session = Depends(get_session)):
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

    output_path = chatterbox_service.synthesize(
        payload.text,
        voice_prompt,
        exaggeration=payload.exaggeration,
        cfg_weight=payload.cfg_weight,
    )
    return FileResponse(path=output_path, media_type="audio/wav", filename="speech.wav")


@router.post("/v1/audio/speech")
def openai_compatible_speech(payload: TTSRequest, session: Session = Depends(get_session)):
    return create_speech(payload, session)

