import subprocess
from datetime import datetime, timezone
from pathlib import Path

from app.media_probe import probe_video
from app.scanner import iter_video_files
from tests.conftest import make_client


def test_scanner_filters_extensions(tmp_path: Path) -> None:
    (tmp_path / "a.mp4").write_bytes(b"a")
    (tmp_path / "b.mkv").write_bytes(b"b")
    (tmp_path / "c.txt").write_bytes(b"c")

    results = iter_video_files(tmp_path)
    names = sorted(path.name for path in results)
    assert names == ["a.mp4", "b.mkv"]


def test_probe_video_fallback_on_error(monkeypatch) -> None:
    def _raise(*args, **kwargs):
        raise subprocess.CalledProcessError(returncode=1, cmd="ffprobe")

    monkeypatch.setattr("subprocess.run", _raise)
    result = probe_video(Path("/tmp/missing.mp4"))

    assert result.duration is None
    assert result.width is None
    assert result.height is None
    assert result.video_codec is None
    assert result.audio_codec is None


def _insert_video_with_date(tmp_path, title, relative_path, created_at):
    from app.database import SessionLocal
    from app.models import Video
    db = SessionLocal()
    v = Video(
        title=title,
        filename=relative_path.split("/")[-1],
        relative_path=relative_path,
        absolute_path=str(tmp_path / "videos" / relative_path),
        extension=".mp4",
        size=1000,
        modified_ts=1000.0,
        folder_path="",
        compatibility_status="direct_play",
        compatibility_reason="test",
        indexed_at=created_at,
        created_at=created_at,
    )
    db.add(v)
    db.commit()
    db.refresh(v)
    db.close()
    return v.id


def test_default_sort_newest_first(tmp_path: Path) -> None:
    """GET /api/videos must return newest videos first by default."""
    from datetime import timedelta
    client = make_client(tmp_path)

    now = datetime.now(timezone.utc)
    _insert_video_with_date(tmp_path, "Old Video", "old.mp4", now - timedelta(days=10))
    _insert_video_with_date(tmp_path, "New Video", "new.mp4", now - timedelta(days=1))

    response = client.get("/api/videos")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["title"] == "New Video"
    assert data[1]["title"] == "Old Video"


def test_sort_oldest_first(tmp_path: Path) -> None:
    """GET /api/videos?sort=created_at&order=asc must return oldest first."""
    from datetime import timedelta
    client = make_client(tmp_path)

    now = datetime.now(timezone.utc)
    _insert_video_with_date(tmp_path, "Old Video", "old2.mp4", now - timedelta(days=10))
    _insert_video_with_date(tmp_path, "New Video", "new2.mp4", now - timedelta(days=1))

    response = client.get("/api/videos?sort=created_at&order=asc")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["title"] == "Old Video"
    assert data[1]["title"] == "New Video"
