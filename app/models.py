from datetime import UTC, datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class VoiceProfile(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    language: str = "en"
    reference_audio_path: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TrainingJob(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    dataset_path: str
    base_model: str = "chatterbox-tts"
    status: str = Field(default="queued", index=True)
    output_model_path: Optional[str] = None
    logs_path: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SynthesisJob(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    text: str
    voice_profile_id: Optional[int] = None
    status: str = Field(default="queued", index=True)
    output_audio_path: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
