#:sdk Aspire.AppHost.Sdk@13.3.1
#:package Aspire.Hosting.Redis@13.4.6

var builder = DistributedApplication.CreateBuilder(args);

// Redis cache
var redis = builder.AddRedis("redis")
    .WithRedisCommander();

// Python FastAPI application
var api = builder.AddExecutable("api", "python", "../")
    .WithArgs(["-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"])
    .WithHttpEndpoint(targetPort: 8000, name: "http")
    .WithReference(redis)
    .WaitFor(redis)
    .WithUrl("/admin", "Admin Portal");

// Python worker service
builder.AddExecutable("worker", "python", "../")
    .WithArgs(["-m", "worker.worker"])
    .WithReference(redis)
    .WaitFor(redis);

builder.Build().Run();
