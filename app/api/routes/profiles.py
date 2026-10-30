import importlib.util
import io
import logging
import shutil
import subprocess
import wave
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlmodel import Session, select

from app.db import get_session
from app.models import VoiceProfile
from app.observability import get_tracer
from app.schemas import VoiceProfileCreate

router = APIRouter(prefix="/profiles", tags=["profiles"])
logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)

_SOUNDFILE_AVAILABLE = importlib.util.find_spec("soundfile") is not None

_UNSUPPORTED_FORMAT_DETAIL = (
    "Unsupported audio format. The TTS model requires a format readable by libsndfile "
    "(e.g. WAV, FLAC, OGG). MP3, AAC, and other compressed formats are not supported. "
    "Convert first with: ffmpeg -i input.mp3 -ar 22050 -ac 1 output.wav"
)
_EMPTY_AUDIO_DETAIL = "Reference audio is empty. Upload a non-empty audio clip."

_M4A_CONTENT_TYPES = {
    "audio/mp4",
    "audio/x-m4a",
    "audio/m4a",
}


def _is_m4a_upload(filename: str, content_type: str | None) -> bool:
    return filename.lower().endswith(".m4a") or (content_type or "").lower() in _M4A_CONTENT_TYPES


def _convert_m4a_to_wav(content: bytes) -> bytes:
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                "pipe:0",
                "-ar",
                "22050",
                "-ac",
                "1",
                "-f",
                "wav",
                "pipe:1",
            ],
            input=content,
            capture_output=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=422,
            detail="M4A uploads require ffmpeg to be installed on the server.",
        ) from exc
    except subprocess.CalledProcessError as exc:
        logger.warning("Failed to transcode M4A upload with ffmpeg.", exc_info=exc)
        raise HTTPException(
            status_code=422,
            detail="Could not process M4A upload. Please re-encode the file to WAV and try again.",
        ) from exc
    return result.stdout


def _validate_audio_format(content: bytes) -> None:
    """Reject unreadable or empty audio; validate WAVs without the TTS extra too."""
    if not content:
        raise HTTPException(status_code=422, detail=_EMPTY_AUDIO_DETAIL)
    if not _SOUNDFILE_AVAILABLE:
        if content.startswith(b"RIFF"):
            try:
                with wave.open(io.BytesIO(content), "rb") as wav_file:
                    frames = wav_file.getnframes()
            except (wave.Error, EOFError) as exc:
                logger.warning("Rejected invalid WAV reference audio.", exc_info=exc)
                raise HTTPException(status_code=422, detail=_UNSUPPORTED_FORMAT_DETAIL) from exc
            if frames <= 0:
                raise HTTPException(status_code=422, detail=_EMPTY_AUDIO_DETAIL)
        return
    import soundfile as sf  # type: ignore

    try:
        info = sf.info(io.BytesIO(content))
    except Exception as exc:
        logger.warning("Rejected reference audio upload because libsndfile could not read the file.", exc_info=exc)
        raise HTTPException(status_code=422, detail=_UNSUPPORTED_FORMAT_DETAIL) from exc
    if info.frames <= 0:
        raise HTTPException(status_code=422, detail=_EMPTY_AUDIO_DETAIL)


@router.get("")
def list_profiles(session: Session = Depends(get_session)):
    return session.exec(select(VoiceProfile)).all()


@router.post("")
def create_profile(payload: VoiceProfileCreate, session: Session = Depends(get_session)):
    with tracer.start_as_current_span("profiles.create_profile") as span:
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

        span.set_attribute("voice_profile.id", profile.id or 0)
        span.set_attribute("voice_profile.language", profile.language)
        logger.info("Created voice profile %s (%s)", profile.id, profile.name)
        return profile


@router.post("/{profile_id}/reference-audio")
async def upload_reference_audio(
    profile_id: int,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    with tracer.start_as_current_span("profiles.upload_reference_audio") as span:
        span.set_attribute("voice_profile.id", profile_id)
        span.set_attribute("upload.filename", file.filename or "")

        profile = session.get(VoiceProfile, profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found.")

        content = await file.read()
        span.set_attribute("upload.size_bytes", len(content))
        filename = Path((file.filename or "reference-audio.wav").replace("\\", "/")).name
        if filename in {"", ".", ".."}:
            raise HTTPException(status_code=422, detail="Invalid reference audio filename.")
        if _SOUNDFILE_AVAILABLE:
            try:
                _validate_audio_format(content)
            except HTTPException:
                if not _is_m4a_upload(filename, file.content_type):
                    raise
                content = _convert_m4a_to_wav(content)
                filename = f"{Path(filename).stem}.wav"
                _validate_audio_format(content)
        else:
            _validate_audio_format(content)

        target_dir = Path("audio") / "profiles" / str(profile_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = target_dir / filename
        target_file.write_bytes(content)

        profile.reference_audio_path = str(target_file)
        session.add(profile)
        session.commit()
        session.refresh(profile)
        logger.info("Stored reference audio for voice profile %s at %s", profile_id, target_file)
        return profile


@router.delete("/{profile_id}")
def delete_profile(profile_id: int, session: Session = Depends(get_session)):
    with tracer.start_as_current_span("profiles.delete_profile") as span:
        span.set_attribute("voice_profile.id", profile_id)

        profile = session.get(VoiceProfile, profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found.")

        profile_audio_dir = Path("audio") / "profiles" / str(profile_id)
        profiles_root = (Path("audio") / "profiles").resolve()
        if profile_audio_dir.is_symlink() or profile_audio_dir.resolve().parent != profiles_root:
            logger.error("Refusing to delete voice profile %s: audio directory is outside profile storage.", profile_id)
            raise HTTPException(status_code=409, detail="Profile audio directory is outside profile storage.")
        try:
            if profile_audio_dir.exists():
                shutil.rmtree(profile_audio_dir)
        except OSError as exc:
            logger.exception("Could not remove audio for voice profile %s", profile_id)
            raise HTTPException(status_code=500, detail="Could not remove profile audio. Please try again.") from exc

        profile_name = profile.name
        session.delete(profile)
        session.commit()

        logger.info("Deleted voice profile %s (%s)", profile_id, profile_name)
        return {"status": "deleted", "profile_id": profile_id}
