from pathlib import Path
import time

from app.config import settings


def run_finetune(training_job_id: int) -> str:
    output_dir = Path(settings.model_storage_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_model = output_dir / f"finetuned-{training_job_id}.ckpt"

    # Placeholder for full fine-tuning orchestration.
    time.sleep(2)
    output_model.write_text("placeholder-checkpoint", encoding="utf-8")
    return str(output_model)

