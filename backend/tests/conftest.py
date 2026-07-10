"""Shared test helpers for database isolation."""
import os
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker


def setup_test_db(tmp_path: Path):
    """Configure environment variables and override the database engine for isolation."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    os.environ["VIDEO_LIBRARY_PATH"] = str(tmp_path / "videos")
    os.environ["DATABASE_PATH"] = str(data_dir / "app.db")
    os.environ["THUMBNAILS_PATH"] = str(tmp_path / "thumbnails")
    os.environ["CACHE_PATH"] = str(tmp_path / "cache")
    os.environ["HLS_OUTPUT_PATH"] = str(tmp_path / "cache" / "hls")
    os.environ["LOGS_PATH"] = str(tmp_path / "logs")

    from app.config import get_settings
    get_settings.cache_clear()

    import app.database as db_module

    new_engine = db_module.create_sqlite_engine(data_dir / "app.db")
    db_module.engine = new_engine
    db_module.SessionLocal = sessionmaker(
        bind=new_engine, autocommit=False, autoflush=False, class_=Session
    )

    # Import all models before create_all
    import app.models  # noqa: F401
    from app.database import Base
    Base.metadata.create_all(bind=new_engine)

    return new_engine


def make_client(tmp_path: Path):
    """Set up isolated test database and return a TestClient."""
    setup_test_db(tmp_path)
    from app.main import app
    from fastapi.testclient import TestClient
    return TestClient(app)
