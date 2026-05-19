from fastapi import APIRouter

from app.config import get_settings
from app.schemas import HealthResponse

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        runtime_dirs={
            "database": str(settings.database_path.parent),
            "thumbnails": str(settings.thumbnails_path),
            "cache": str(settings.cache_path),
            "hls": str(settings.hls_output_path),
            "logs": str(settings.logs_path),
        },
    )

