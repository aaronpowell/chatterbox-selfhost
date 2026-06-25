from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlmodel import Session, select

from app.db import get_session
from app.models import VoiceProfile
from app.schemas import VoiceProfileCreate

router = APIRouter(prefix="/profiles", tags=["profiles"])


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

    target_dir = Path("audio") / "profiles" / str(profile_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = target_dir / file.filename
    content = await file.read()
    target_file.write_bytes(content)

    profile.reference_audio_path = str(target_file)
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile

