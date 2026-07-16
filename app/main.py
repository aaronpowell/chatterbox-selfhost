from contextlib import asynccontextmanager
import logging
from pathlib import Path
import time
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.api.routes.health import router as health_router
from app.api.routes.profiles import router as profiles_router
from app.api.routes.training import router as training_router
from app.api.routes.tts import router as tts_router
from app.config import settings
from app.db import create_db_and_tables, engine
from app.observability import configure_observability, instrument_fastapi_app, instrument_sqlalchemy_engine, request_context
from app.services.storage import ensure_storage_dirs

configure_observability(
    service_name=f"{settings.app_name}-api",
    environment=settings.app_env,
    log_level=settings.log_level,
    enable_tracing=settings.enable_tracing,
    otlp_endpoint=settings.otlp_endpoint,
    otlp_protocol=settings.otlp_protocol,
    seq_uri=settings.seq_uri,
)
logger = logging.getLogger("app.request")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_storage_dirs()
    create_db_and_tables()
    instrument_sqlalchemy_engine(engine)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
instrument_fastapi_app(app)
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@app.middleware("http")
async def log_request(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid4().hex
    start_time = time.perf_counter()

    with request_context(request_id):
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "Unhandled request error for %s %s after %.2fms",
                request.method,
                request.url.path,
                (time.perf_counter() - start_time) * 1000,
            )
            raise

        duration_ms = (time.perf_counter() - start_time) * 1000
        response.headers["X-Request-ID"] = request_id

        if request.url.path == "/health":
            log_level = logging.DEBUG
        elif response.status_code >= 500:
            log_level = logging.ERROR
        elif response.status_code >= 400:
            log_level = logging.WARNING
        else:
            log_level = logging.INFO

        logger.log(
            log_level,
            "%s %s -> %s in %.2fms",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response


@app.get("/admin", response_class=HTMLResponse, tags=["admin"])
def admin(request: Request):
    return templates.TemplateResponse(request=request, name="admin.html", context={"app_name": settings.app_name})


app.include_router(health_router)
app.include_router(profiles_router)
app.include_router(tts_router)
app.include_router(training_router)
