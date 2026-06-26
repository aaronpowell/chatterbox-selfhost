from datetime import datetime, timezone
import logging
from pathlib import Path
import traceback

from opentelemetry.trace import SpanKind, Status, StatusCode
from sqlmodel import Session

from app.config import settings
from app.db import engine
from app.models import TrainingJob
from app.observability import extract_trace_context, get_tracer
from trainer.runner import run_finetune

logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)


def _append_job_log(logs_path: Path, message: str) -> None:
    with logs_path.open("a", encoding="utf-8") as handle:
        handle.write(message)


def run_training_job(training_job_id: int, trace_context: dict[str, str] | None = None):
    parent_context = extract_trace_context(trace_context)
    with tracer.start_as_current_span("worker.run_training_job", context=parent_context, kind=SpanKind.CONSUMER) as span:
        span.set_attribute("training.job.id", training_job_id)

        with Session(engine) as session:
            job = session.get(TrainingJob, training_job_id)
            if not job:
                span.set_status(Status(StatusCode.ERROR, "Training job not found"))
                logger.error("Training job %s was not found before execution started.", training_job_id)
                return
            job.status = "running"
            job.updated_at = datetime.utcnow()
            session.add(job)
            session.commit()

        logs_path = Path(settings.job_storage_path) / f"training-{training_job_id}.log"
        logs_path.parent.mkdir(parents=True, exist_ok=True)
        _append_job_log(logs_path, f"[{datetime.now(timezone.utc).isoformat()}] Starting training job {training_job_id}\n")

        try:
            output_model = run_finetune(training_job_id)
            with Session(engine) as session:
                job = session.get(TrainingJob, training_job_id)
                if not job:
                    span.set_status(Status(StatusCode.ERROR, "Training job disappeared during completion"))
                    logger.error("Training job %s disappeared before completion could be persisted.", training_job_id)
                    return
                job.status = "completed"
                job.output_model_path = output_model
                job.logs_path = str(logs_path)
                job.updated_at = datetime.utcnow()
                session.add(job)
                session.commit()
            _append_job_log(
                logs_path,
                f"[{datetime.now(timezone.utc).isoformat()}] Training job completed. Output model: {output_model}\n",
            )
            logger.info("Training job %s completed with output model %s", training_job_id, output_model)
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            logger.exception("Training job %s failed.", training_job_id)
            with Session(engine) as session:
                job = session.get(TrainingJob, training_job_id)
                if not job:
                    logger.error("Training job %s disappeared while persisting the failure state.", training_job_id)
                    return
                job.status = "failed"
                job.logs_path = str(logs_path)
                job.updated_at = datetime.utcnow()
                session.add(job)
                session.commit()
            _append_job_log(
                logs_path,
                (
                    f"[{datetime.now(timezone.utc).isoformat()}] Training failed: {exc}\n"
                    f"{traceback.format_exc()}"
                ),
            )
