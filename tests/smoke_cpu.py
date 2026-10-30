"""Run inside the built CPU image; no model downloads or Redis are required."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory


def main():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        os.environ.update(
            DATABASE_URL=f"sqlite:///{root / 'app.db'}",
            AUDIO_STORAGE_PATH=str(root / "audio"),
            MODEL_STORAGE_PATH=str(root / "models"),
            JOB_STORAGE_PATH=str(root / "jobs"),
            ENABLE_TRACING="false",
            TTS_DEVICE="cpu",
        )

        import torch
        import torchaudio
        from chatterbox.tts import ChatterboxTTS
        from fastapi.testclient import TestClient

        from app.main import app
        from app.services.chatterbox_service import chatterbox_service, _resolve_tts_device
        from worker.worker import main as worker_main

        assert torch.version.cuda is None, "CPU image must not depend on CUDA"
        assert _resolve_tts_device() == "cpu"
        assert chatterbox_service.is_available, "Speech dependencies are missing"
        assert callable(ChatterboxTTS.from_pretrained)
        assert callable(worker_main)

        audio = root / "smoke.wav"
        torchaudio.save(str(audio), torch.zeros(1, 2400), 24000)
        waveform, sample_rate = torchaudio.load(str(audio))
        assert waveform.shape == (1, 2400)
        assert sample_rate == 24000
        assert audio.stat().st_size > 44

        with TestClient(app) as client:
            assert client.get("/health").status_code == 200
            assert client.get("/admin").status_code == 200

        print("CPU TTS imports, WAV round trip, API startup and worker import passed.")


if __name__ == "__main__":
    main()
