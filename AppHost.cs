#:sdk Aspire.AppHost.Sdk@13.3.1
#:package Aspire.Hosting.Redis@13.4.6
#:package Aspire.Hosting.Python@13.4.6

var builder = DistributedApplication.CreateBuilder(args);

// Redis cache
var redis = builder.AddRedis("redis")
    .WithRedisCommander();

// Python FastAPI application — AddUvicornApp manages the venv and runs uvicorn
var api = builder.AddUvicornApp("api", ".", "app.main:app")
    .WithVirtualEnvironment(".venv-api")
    .WithHttpEndpoint(port: 8000, env: "UVICORN_PORT")
    .WithHttpHealthCheck("/health")
    .WithEnvironment("UVICORN_RELOAD", "true")
    .WithReference(redis)
    .WaitFor(redis)
    .WithUrl("/admin", "Admin Portal");

// Python worker service — isolated venv mirrors independent container deployment
builder.AddPythonModule("worker", ".", "worker.worker")
    .WithVirtualEnvironment(".venv-worker")
    .WithReference(redis)
    .WaitFor(redis);

builder.Build().Run();
