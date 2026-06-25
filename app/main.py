from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.api.routes.health import router as health_router
from app.api.routes.profiles import router as profiles_router
from app.api.routes.training import router as training_router
from app.api.routes.tts import router as tts_router
from app.config import settings
from app.db import create_db_and_tables
from app.services.storage import ensure_storage_dirs


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_storage_dirs()
    create_db_and_tables()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@app.get("/admin", response_class=HTMLResponse, tags=["admin"])
def admin(request: Request):
    return templates.TemplateResponse(request=request, name="admin.html", context={"app_name": settings.app_name})


app.include_router(health_router)
app.include_router(profiles_router)
app.include_router(tts_router)
app.include_router(training_router)
