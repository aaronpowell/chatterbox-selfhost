import importlib.util
import io
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlmodel import Session, select

from app.db import get_session
from app.models import VoiceProfile
from app.schemas import VoiceProfileCreate

router = APIRouter(prefix="/profiles", tags=["profiles"])

_SOUNDFILE_AVAILABLE = importlib.util.find_spec("soundfile") is not None

_UNSUPPORTED_FORMAT_DETAIL = (
    "Unsupported audio format. The TTS model requires a format readable by libsndfile "
    "(e.g. WAV, FLAC, OGG). MP3, AAC, M4A, and other compressed formats are not supported. "
    "Convert first with: ffmpeg -i input.mp3 -ar 22050 -ac 1 output.wav"
)


def _validate_audio_format(content: bytes) -> None:
    """Raise HTTPException 422 if the audio bytes are not readable by libsndfile.

    Only runs when soundfile is installed (i.e. the tts extra is present).
    Skips validation silently in stripped environments so the API still boots.
    """
    if not _SOUNDFILE_AVAILABLE:
        return
    import soundfile as sf  # type: ignore

    try:
        sf.info(io.BytesIO(content))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=_UNSUPPORTED_FORMAT_DETAIL) from exc


@router.get("")
def list_profiles(session: Session = Depends(get_session)):
    return session.exec(select(VoiceProfile)).all()


@router.post("")
def create_profile(payload: VoiceProfileCreate, session: Session = Depends(get_session)):
    existing = session.exec(select(VoiceProfile).where(VoiceProfile.name == payload.name)).first()
    if existing:
        raise HTTPException(status_code=409, detail="Profile name already exists.")
    profile = VoiceProfile(
        name=payload.name,
        language=payload.language,
        reference_audio_path="",
    )
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile


@router.post("/{profile_id}/reference-audio")
async def upload_reference_audio(
    profile_id: int,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    profile = session.get(VoiceProfile, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found.")

    content = await file.read()
    _validate_audio_format(content)

    target_dir = Path("audio") / "profiles" / str(profile_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = target_dir / file.filename
    target_file.write_bytes(content)

    profile.reference_audio_path = str(target_file)
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile

