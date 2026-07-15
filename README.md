# chatterbox-selfhost

Self-hosted Chatterbox API with:

- OpenAI-compatible speech endpoint
- Voice profile management with sample clips
- Fine-tuning job orchestration surface
- Web admin portal
- GHCR-ready CPU/CUDA containers

## Quick start

### With .NET Aspire (file-based AppHost)

```bash
dotnet run Aspire.Host.AppHost/AppHost.cs
```

This orchestrates:
- Redis cache with RedisCommander UI
- FastAPI API server (with hot reload)
- Background worker service

Open:

- AppHost dashboard: `http://localhost:15000`
- API docs: `http://localhost:8000/docs` (once services start)
- RedisCommander: Available in dashboard resources

### Manual setup

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

Observability-related settings:

- `LOG_LEVEL` controls application and worker verbosity.
- `ENABLE_TRACING` enables OpenTelemetry span creation for API requests, database work, queue handoffs, and worker execution.
- `OTEL_EXPORTER_OTLP_ENDPOINT` points at your OTLP HTTP traces endpoint.
- `SEQ_URI` is also supported as a shortcut; traces will be exported to `${SEQ_URI}/ingest/otlp/v1/traces`.
- `TTS_DEVICE` controls model device selection: `auto` (default), `cpu`, or `cuda`.
  - `auto` uses CUDA when available, otherwise CPU.
  - On Windows for CUDA, this repo configures `uv` to install `torch`/`torchaudio` from the PyTorch CUDA 12.6 wheel index.

## Docker

Generate Compose artifacts from the AppHost model:

```bash
aspire publish --non-interactive
```

Build and deploy locally with the Aspire Docker Compose pipeline:

```bash
aspire deploy --non-interactive
```

Build and push app images to GHCR from the AppHost model:

```bash
REGISTRY_ENDPOINT=ghcr.io REGISTRY_REPOSITORY=aaronpowell/chatterbox-selfhost aspire do push --non-interactive
```

## Notes

- Fine-tuning API is scaffolded in v1 and wired for queue execution; the training runner is intentionally isolated in `trainer/` so compute/runtime choices stay flexible.
- Inference uses official `chatterbox-tts` dependency.
