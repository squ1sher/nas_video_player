import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi import Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import Base, engine
# Import all models so create_all picks them up
import app.models  # noqa: F401
from app.migrations import run_migrations
from app.routes.duplicates import router as duplicates_router
from app.routes.folders import router as folders_router
from app.routes.health import router as health_router
from app.routes.hls import global_hls_router, video_hls_router
from app.routes.library import router as library_router
from app.routes.maintenance import router as maintenance_router
from app.routes.media_profiles import router as media_profiles_router
from app.routes.progress import router as progress_router
from app.routes.scan import router as scan_router
from app.routes.settings import router as settings_router
from app.routes.tags import router as tags_router
from app.routes.videos import router as videos_router
from app.scanner import initialize_library_roots, recover_scan_runtime_state
from app.services.hls_service import ensure_batch_worker_started, recover_hls_runtime_state
from app.utils.logging_config import configure_logging

settings = get_settings()
settings.ensure_runtime_dirs()
configure_logging(settings.logs_path)

logger = logging.getLogger(__name__)

app = FastAPI(title="NAS Video Player", version="0.2.6")

app.include_router(health_router)
app.include_router(scan_router)
app.include_router(settings_router)
app.include_router(library_router)
app.include_router(media_profiles_router)
app.include_router(maintenance_router)
# progress_router MUST come before videos_router so /continue-watching
# is matched before /{video_id}
app.include_router(progress_router)
app.include_router(folders_router)
app.include_router(duplicates_router)
app.include_router(global_hls_router)
app.include_router(video_hls_router)
app.include_router(tags_router)
app.include_router(videos_router)


@app.on_event("startup")
def on_startup() -> None:
    import app.database as _db_module
    Base.metadata.create_all(bind=engine)
    run_migrations(engine)
    db = _db_module.SessionLocal()
    try:
        initialize_library_roots(db, settings)
    finally:
        db.close()
    recover_scan_runtime_state()
    recover_hls_runtime_state()
    ensure_batch_worker_started()
    logger.info("Application started")
    logger.info("Video library path: %s", settings.video_library_path)


static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")


@app.get("/", response_model=None)
def serve_root() -> Response:
    index_file = static_dir / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return JSONResponse({"message": "Frontend build not found"}, status_code=404)


@app.get("/{full_path:path}", response_model=None)
def serve_spa(full_path: str) -> Response:
    if full_path.startswith("api/"):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    requested = static_dir / full_path
    if requested.exists() and requested.is_file():
        return FileResponse(requested)

    index_file = static_dir / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return JSONResponse({"message": "Frontend build not found"}, status_code=404)
