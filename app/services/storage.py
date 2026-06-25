from pathlib import Path

from app.config import settings


def ensure_storage_dirs() -> None:
    for folder in (
        settings.audio_storage_path,
        settings.model_storage_path,
        settings.job_storage_path,
        "data",
    ):
        Path(folder).mkdir(parents=True, exist_ok=True)

