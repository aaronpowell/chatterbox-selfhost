from pathlib import Path
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine

from app.models import TrainingJob
from worker import tasks as worker_tasks


def test_create_training_job_enqueues_trace_context(client):
    with (
        patch("app.api.routes.training.get_redis_connection", return_value=object()),
        patch("app.api.routes.training.Queue") as queue_cls,
    ):
        response = client.post(
            "/training/jobs",
            json={"dataset_path": "/tmp/dataset", "base_model": "chatterbox-tts"},
        )

    assert response.status_code == 200
    queue = queue_cls.return_value
    queue.enqueue.assert_called_once()
    _, kwargs = queue.enqueue.call_args
    assert "trace_context" in kwargs
    assert kwargs["trace_context"]["traceparent"].startswith("00-")


def test_failed_training_job_writes_traceback(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        job = TrainingJob(dataset_path="dataset", base_model="chatterbox-tts", status="queued")
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = job.id

    monkeypatch.setattr(worker_tasks, "engine", engine)
    monkeypatch.setattr(worker_tasks.settings, "job_storage_path", str(tmp_path))

    with patch("worker.tasks.run_finetune", side_effect=RuntimeError("boom")):
        worker_tasks.run_training_job(job_id)

    with Session(engine) as session:
        stored_job = session.get(TrainingJob, job_id)
        assert stored_job is not None
        assert stored_job.status == "failed"
        assert stored_job.logs_path is not None

    log_path = Path(stored_job.logs_path)
    contents = log_path.read_text(encoding="utf-8")
    assert "Training failed: boom" in contents
    assert "Traceback" in contents
