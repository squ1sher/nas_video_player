import os
from pathlib import Path

from fastapi.testclient import TestClient


def test_health_endpoint(tmp_path: Path) -> None:
    os.environ["VIDEO_LIBRARY_PATH"] = str(tmp_path / "videos")
    os.environ["DATABASE_PATH"] = str(tmp_path / "data" / "app.db")
    os.environ["THUMBNAILS_PATH"] = str(tmp_path / "thumbnails")
    os.environ["CACHE_PATH"] = str(tmp_path / "cache")
    os.environ["LOGS_PATH"] = str(tmp_path / "logs")

    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import app

    client = TestClient(app)
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

