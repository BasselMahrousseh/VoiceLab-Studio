"""VoiceLab Studio — scripted Emirati voice-recording and dataset-QC platform.

Run (from repo root):
    .venv/Scripts/python -m uvicorn app.main:app --app-dir backend --port 8000

Serves the API under /api and, when frontend/dist exists, the built SPA at /.
"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .db import init_db
from .deps import get_current_user, get_user_flexible, require_admin, require_admin_flexible
from .routers import (
    auth,
    datasets,
    exports,
    recorder,
    recordings,
    scripts,
    sessions,
    speakers,
    status,
)

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)

# Dev convenience: allow the Vite dev server origin. In production the SPA is
# served from the same origin, so this list is inert.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Public: only login is reachable without a token (its own handler checks
# credentials). Everything else requires an authenticated user; admin-only
# surfaces additionally require the admin role.
app.include_router(auth.router, prefix="/api")
app.include_router(status.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(sessions.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(recordings.router, prefix="/api", dependencies=[Depends(get_user_flexible)])
app.include_router(recorder.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(scripts.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(speakers.router, prefix="/api", dependencies=[Depends(require_admin)])
app.include_router(datasets.router, prefix="/api")  # router requires admin
app.include_router(exports.router, prefix="/api", dependencies=[Depends(require_admin_flexible)])


# --- static frontend (production build) --------------------------------------
_here = Path(__file__).resolve()
_dist = _here.parent.parent.parent / "frontend" / "dist"
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        candidate = _dist / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_dist / "index.html")
