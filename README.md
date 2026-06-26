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
