from typing import Optional

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    app: str


class VoiceProfileCreate(BaseModel):
    name: str = Field(min_length=2, max_length=64)
    language: str = Field(default="en", min_length=2, max_length=16)


class VoiceProfileRead(BaseModel):
    id: int
    name: str
    language: str
    reference_audio_path: str


class TTSRequest(BaseModel):
    text: str = Field(min_length=1)
    voice_profile_id: Optional[int] = None
    format: str = "wav"
    exaggeration: float = Field(default=0.5, ge=0.0, le=1.0)
    cfg_weight: float = Field(default=0.5, ge=0.0, le=1.0)


class TrainingJobCreate(BaseModel):
    dataset_path: str
    base_model: str = "chatterbox-tts"

