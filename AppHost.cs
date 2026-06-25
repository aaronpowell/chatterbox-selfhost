#:sdk Aspire.AppHost.Sdk@13.3.1
#:package Aspire.Hosting.Redis@13.4.6
#:package Aspire.Hosting.Python@13.4.6

var builder = DistributedApplication.CreateBuilder(args);

// Redis cache
var redis = builder.AddRedis("redis")
    .WithRedisCommander();

// Python FastAPI application — AddUvicornApp manages the venv and runs uvicorn
var api = builder.AddUvicornApp("api", ".", "app.main:app")
    .WithHttpEndpoint(port: 8000, env: "UVICORN_PORT")
    .WithHttpHealthCheck("/health")
    .WithEnvironment("UVICORN_RELOAD", "true")
    .WithReference(redis)
    .WaitFor(redis)
    .WithUrl("/admin", "Admin Portal");

// Python worker service — shares the same venv as the api; wait for api to
// finish venv setup before starting (avoids a Windows file-lock race on .venv)
builder.AddPythonModule("worker", ".", "worker.worker")
    .WithReference(redis)
    .WaitFor(redis)
    .WaitFor(api);

builder.Build().Run();
