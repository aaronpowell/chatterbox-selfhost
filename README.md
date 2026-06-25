# chatterbox-selfhost

Self-hosted Chatterbox API with:

- OpenAI-compatible speech endpoint
- Voice profile management with sample clips
- Fine-tuning job orchestration surface
- Web admin portal
- GHCR-ready CPU/CUDA containers

## Quick start

```bash
python -m venv .venv
. .venv/Scripts/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

Open:

- API docs: `http://localhost:8000/docs`
- Admin portal: `http://localhost:8000/admin`

## Environment

Copy `.env.example` to `.env` and adjust values.

## Docker

CPU:

```bash
docker build -f Dockerfile.cpu -t ghcr.io/aaronpowell/chatterbox-selfhost:cpu .
```

CUDA:

```bash
docker build -f Dockerfile.cuda -t ghcr.io/aaronpowell/chatterbox-selfhost:cuda .
```

Compose:

```bash
docker compose up -d
```

## Notes

- Fine-tuning API is scaffolded in v1 and wired for queue execution; the training runner is intentionally isolated in `trainer/` so compute/runtime choices stay flexible.
- Inference uses official `chatterbox-tts` dependency.

