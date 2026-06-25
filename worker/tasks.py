from datetime import datetime
from pathlib import Path

from sqlmodel import Session

from app.config import settings
from app.db import engine
from app.models import TrainingJob
from trainer.runner import run_finetune


def run_training_job(training_job_id: int):
    with Session(engine) as session:
        job = session.get(TrainingJob, training_job_id)
        if not job:
            return
        job.status = "running"
        job.updated_at = datetime.utcnow()
        session.add(job)
        session.commit()

    logs_path = Path(settings.job_storage_path) / f"training-{training_job_id}.log"
    logs_path.parent.mkdir(parents=True, exist_ok=True)
    logs_path.write_text("Starting training job\n", encoding="utf-8")

    try:
        output_model = run_finetune(training_job_id)
        with Session(engine) as session:
            job = session.get(TrainingJob, training_job_id)
            if not job:
                return
            job.status = "completed"
            job.output_model_path = output_model
            job.logs_path = str(logs_path)
            job.updated_at = datetime.utcnow()
            session.add(job)
            session.commit()
    except Exception as exc:
        with Session(engine) as session:
            job = session.get(TrainingJob, training_job_id)
            if not job:
                return
            job.status = "failed"
            job.logs_path = str(logs_path)
            job.updated_at = datetime.utcnow()
            session.add(job)
            session.commit()
        logs_path.write_text(f"Training failed: {exc}\n", encoding="utf-8")
