#:sdk Aspire.AppHost.Sdk@13.3.1
#:package Aspire.Hosting.Redis@13.4.6
#:package Aspire.Hosting.Python@13.4.6

var builder = DistributedApplication.CreateBuilder(args);

// Redis cache
var redis = builder.AddRedis("redis")
    .WithRedisCommander();

// Python FastAPI application — AddUvicornApp uses uv to sync deps and run uvicorn.
// Sync the optional `tts` extra so the Chatterbox model (torch, etc.) is present
// and real speech synthesis works, not just graceful degradation.
var api = builder.AddUvicornApp("api", ".", "app.main:app")
    .WithUv(args: ["sync", "--extra", "tts"])
    .WithHttpEndpoint(port: 8000, env: "UVICORN_PORT")
    .WithHttpHealthCheck("/health")
    .WithEnvironment("UVICORN_RELOAD", "true")
    .WithReference(redis)
    .WaitFor(redis)
    .WithUrl("/admin", "Admin Portal");

// Python worker service. api and worker are one uv project (shared pyproject +
// .venv); wait for the api to finish syncing so the two `uv sync` runs don't
// race on the same environment. Both must request the same `--extra tts` so the
// second sync doesn't prune the TTS packages out of the shared venv. Deployment
// isolation is handled per-service by the container images, not by dev venvs.
builder.AddPythonModule("worker", ".", "worker.worker")
    .WithUv(args: ["sync", "--extra", "tts"])
    .WithReference(redis)
    .WaitFor(redis)
    .WaitFor(api);

builder.Build().Run();
