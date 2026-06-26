import logging
from pathlib import Path
import time

from app.config import settings
from app.observability import get_tracer

logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)


def run_finetune(training_job_id: int) -> str:
    with tracer.start_as_current_span("trainer.run_finetune") as span:
        output_dir = Path(settings.model_storage_path)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_model = output_dir / f"finetuned-{training_job_id}.ckpt"

        span.set_attribute("training.job.id", training_job_id)
        span.set_attribute("training.output_model_path", str(output_model))
        logger.info("Starting fine-tuning for training job %s", training_job_id)

        # Placeholder for full fine-tuning orchestration.
        time.sleep(2)
        output_model.write_text("placeholder-checkpoint", encoding="utf-8")
        logger.info("Finished fine-tuning for training job %s", training_job_id)
        return str(output_model)
