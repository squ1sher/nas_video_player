from pathlib import Path

from sqlalchemy import text

from tests.conftest import setup_test_db


def test_sqlite_engine_uses_wal_and_busy_timeout(tmp_path: Path) -> None:
    setup_test_db(tmp_path)

    from app.database import SessionLocal

    db = SessionLocal()
    try:
        journal_mode = db.execute(text("PRAGMA journal_mode")).scalar()
        busy_timeout = db.execute(text("PRAGMA busy_timeout")).scalar()
    finally:
        db.close()

    assert str(journal_mode).lower() == "wal"
    assert int(busy_timeout) >= 30000
