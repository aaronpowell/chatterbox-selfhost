from datetime import datetime
import logging

from fastapi import APIRouter, Depends, HTTPException
from rq import Queue
from sqlmodel import Session, select

from app.db import get_session
from app.models import TrainingJob
from app.observability import get_tracer, serialize_current_trace_context
from app.redis_conn import get_redis_connection
from app.schemas import TrainingJobCreate
from worker.tasks import run_training_job

router = APIRouter(prefix="/training", tags=["training"])
logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)


@router.get("/jobs")
def list_training_jobs(session: Session = Depends(get_session)):
    return session.exec(select(TrainingJob)).all()


@router.post("/jobs")
def create_training_job(payload: TrainingJobCreate, session: Session = Depends(get_session)):
    with tracer.start_as_current_span("training.create_job") as span:
        job = TrainingJob(dataset_path=payload.dataset_path, base_model=payload.base_model, status="queued")
        session.add(job)
        session.commit()
        session.refresh(job)

        redis_conn = get_redis_connection()
        queue = Queue("training", connection=redis_conn)
        trace_context = serialize_current_trace_context()
        queue.enqueue(run_training_job, job.id, trace_context=trace_context)

        span.set_attribute("training.job.id", job.id or 0)
        span.set_attribute("training.dataset_path", job.dataset_path)
        span.set_attribute("training.base_model", job.base_model)
        logger.info("Queued training job %s for dataset %s", job.id, job.dataset_path)
        return job


@router.post("/jobs/{job_id}/promote")
def promote_training_job(job_id: int, session: Session = Depends(get_session)):
    with tracer.start_as_current_span("training.promote_job") as span:
        span.set_attribute("training.job.id", job_id)

        job = session.get(TrainingJob, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Training job not found.")
        if job.status != "completed":
            raise HTTPException(status_code=409, detail="Training job is not completed yet.")

        job.updated_at = datetime.utcnow()
        session.add(job)
        session.commit()
        session.refresh(job)
        logger.info("Promoted training job %s", job.id)
        return {"status": "promoted", "job_id": job.id, "model_path": job.output_model_path}
