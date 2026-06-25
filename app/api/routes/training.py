from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from redis import Redis
from rq import Queue
from sqlmodel import Session, select

from app.config import settings
from app.db import get_session
from app.models import TrainingJob
from app.schemas import TrainingJobCreate
from worker.tasks import run_training_job

router = APIRouter(prefix="/training", tags=["training"])


@router.get("/jobs")
def list_training_jobs(session: Session = Depends(get_session)):
    return session.exec(select(TrainingJob)).all()


@router.post("/jobs")
def create_training_job(payload: TrainingJobCreate, session: Session = Depends(get_session)):
    job = TrainingJob(dataset_path=payload.dataset_path, base_model=payload.base_model, status="queued")
    session.add(job)
    session.commit()
    session.refresh(job)

    redis_conn = Redis.from_url(settings.redis_url)
    queue = Queue("training", connection=redis_conn)
    queue.enqueue(run_training_job, job.id)
    return job


@router.post("/jobs/{job_id}/promote")
def promote_training_job(job_id: int, session: Session = Depends(get_session)):
    job = session.get(TrainingJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Training job not found.")
    if job.status != "completed":
        raise HTTPException(status_code=409, detail="Training job is not completed yet.")

    job.updated_at = datetime.utcnow()
    session.add(job)
    session.commit()
    session.refresh(job)
    return {"status": "promoted", "job_id": job.id, "model_path": job.output_model_path}

