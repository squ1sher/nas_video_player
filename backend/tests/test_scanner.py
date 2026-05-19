import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from app.media_probe import ProbeResult, probe_video
from app.scanner import iter_library_files, scan_video_library
from tests.conftest import make_client, setup_test_db


def test_scanner_iterates_all_regular_files(tmp_path: Path) -> None:
    (tmp_path / "a.mp4").write_bytes(b"a")
    (tmp_path / "b.360").write_bytes(b"b")
    (tmp_path / "c.txt").write_bytes(b"c")

    results = iter_library_files(tmp_path)
    names = sorted(path.name for path in results)
    assert names == ["a.mp4", "b.360", "c.txt"]


def test_probe_video_fallback_on_error(monkeypatch) -> None:
    def _raise(*args, **kwargs):
        raise subprocess.CalledProcessError(returncode=1, cmd="ffprobe")

    monkeypatch.setattr("subprocess.run", _raise)
    result = probe_video(Path("/tmp/missing.mp4"))

    assert result.success is False
    assert result.error is not None
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
        media_status="detected_video",
        probe_status="success",
        indexed_at=created_at,
        created_at=created_at,
    )
    db.add(v)
    db.commit()
    db.refresh(v)
    db.close()
    return v.id


def _build_settings(tmp_path: Path):
    from app.config import Settings

    return Settings(
        VIDEO_LIBRARY_PATH=str(tmp_path / "videos"),
        DATABASE_PATH=str(tmp_path / "data" / "app.db"),
        THUMBNAILS_PATH=str(tmp_path / "thumbnails"),
        CACHE_PATH=str(tmp_path / "cache"),
        LOGS_PATH=str(tmp_path / "logs"),
        MEDIA_DISCOVERY_MODE="probe",
        PROBE_UNKNOWN_EXTENSIONS="true",
    )


def _ensure_root(db, tmp_path: Path):
    """Insert a LibraryRoot for tmp_path/videos so scanner tests work without auto-bootstrap."""
    from app.models import LibraryRoot
    root_path = str(tmp_path / "videos")
    existing = db.query(LibraryRoot).filter(LibraryRoot.path == root_path).first()
    if existing:
        return existing
    root = LibraryRoot(
        name="Test Root",
        path=root_path,
        media_type="video",
        enabled=True,
        recursive=True,
        scan_priority=100,
    )
    db.add(root)
    db.commit()
    db.refresh(root)
    return root


def test_probe_unknown_extension_is_indexed(tmp_path: Path, monkeypatch) -> None:
    setup_test_db(tmp_path)
    root = tmp_path / "videos"
    root.mkdir(parents=True)
    (root / "clip.360").write_bytes(b"0" * 2_000_000)

    monkeypatch.setattr(
        "app.scanner.probe_video",
        lambda _p: ProbeResult(success=True, has_video_stream=True, duration=12.0, width=1920, height=1080, video_codec="h264", audio_codec="aac", container_format="mp4"),
    )
    monkeypatch.setattr("app.scanner.ensure_thumbnail", lambda *args, **kwargs: None)

    from app.database import SessionLocal
    from app.models import Video

    db = SessionLocal()
    _ensure_root(db, tmp_path)
    settings = _build_settings(tmp_path)
    result = scan_video_library(db, settings)
    videos = db.query(Video).all()
    db.close()

    assert result.detected_videos == 1
    assert len(videos) == 1
    assert videos[0].extension == ".360"
    assert videos[0].media_status == "detected_video"


def test_uppercase_mpg_extension_normalized(tmp_path: Path, monkeypatch) -> None:
    setup_test_db(tmp_path)
    root = tmp_path / "videos"
    root.mkdir(parents=True)
    (root / "movie.MPG").write_bytes(b"0" * 2_000_000)

    monkeypatch.setattr(
        "app.scanner.probe_video",
        lambda _p: ProbeResult(success=True, has_video_stream=True, duration=100.0, width=1280, height=720, video_codec="mpeg2video", audio_codec="mp2", container_format="mpeg"),
    )
    monkeypatch.setattr("app.scanner.ensure_thumbnail", lambda *args, **kwargs: None)

    from app.database import SessionLocal
    from app.models import Video

    db = SessionLocal()
    _ensure_root(db, tmp_path)
    scan_video_library(db, _build_settings(tmp_path))
    video = db.query(Video).first()
    db.close()

    assert video is not None
    assert video.extension == ".mpg"
    assert video.probe_status == "success"


def test_probe_failure_indexes_possible_video_when_allowed(tmp_path: Path, monkeypatch) -> None:
    setup_test_db(tmp_path)
    root = tmp_path / "videos"
    root.mkdir(parents=True)
    (root / "unknown.360").write_bytes(b"0" * 2_000_000)

    monkeypatch.setattr("app.scanner.probe_video", lambda _p: ProbeResult(success=False, error="ffprobe failed"))

    from app.database import SessionLocal
    from app.models import Video

    db = SessionLocal()
    _ensure_root(db, tmp_path)
    result = scan_video_library(db, _build_settings(tmp_path))
    video = db.query(Video).first()
    db.close()

    assert result.probe_failed == 1
    assert video is not None
    assert video.media_status == "probe_failed_possible_video"
    assert video.compatibility_status == "unknown"


def test_probe_success_without_video_stream_is_ignored(tmp_path: Path, monkeypatch) -> None:
    setup_test_db(tmp_path)
    root = tmp_path / "videos"
    root.mkdir(parents=True)
    (root / "audio_only.flac").write_bytes(b"0" * 2_000_000)

    monkeypatch.setattr(
        "app.scanner.probe_video",
        lambda _p: ProbeResult(success=True, has_video_stream=False, duration=60.0, audio_codec="flac", container_format="flac"),
    )

    from app.database import SessionLocal
    from app.models import Video

    db = SessionLocal()
    _ensure_root(db, tmp_path)
    result = scan_video_library(db, _build_settings(tmp_path))
    count = db.query(Video).count()
    db.close()

    assert result.ignored_non_media >= 1 or result.ignored_excluded >= 1
    assert count == 0


def test_excluded_extensions_are_skipped(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    root = tmp_path / "videos"
    root.mkdir(parents=True)
    (root / "notes.txt").write_bytes(b"0" * 100)

    from app.database import SessionLocal
    from app.models import Video

    db = SessionLocal()
    _ensure_root(db, tmp_path)
    result = scan_video_library(db, _build_settings(tmp_path))
    count = db.query(Video).count()
    db.close()

    assert result.ignored_excluded >= 1
    assert count == 0


def test_thumbnail_failure_does_not_remove_indexed_video(tmp_path: Path, monkeypatch) -> None:
    setup_test_db(tmp_path)
    root = tmp_path / "videos"
    root.mkdir(parents=True)
    (root / "clip.mp4").write_bytes(b"0" * 2_000_000)

    monkeypatch.setattr(
        "app.scanner.probe_video",
        lambda _p: ProbeResult(success=True, has_video_stream=True, duration=12.0, width=1920, height=1080, video_codec="h264", audio_codec="aac", container_format="mp4"),
    )

    def _thumb_raise(*args, **kwargs):
        raise RuntimeError("thumbnail failed")

    monkeypatch.setattr("app.scanner.ensure_thumbnail", _thumb_raise)

    from app.database import SessionLocal
    from app.models import Video

    db = SessionLocal()
    _ensure_root(db, tmp_path)
    result = scan_video_library(db, _build_settings(tmp_path))
    video = db.query(Video).first()
    db.close()

    assert result.thumbnail_errors == 1
    assert video is not None
    assert video.media_status == "detected_video"
    assert video.thumbnail_status == "failed"


def test_api_returns_media_and_compatibility_status(tmp_path: Path) -> None:
    from datetime import timedelta

    client = make_client(tmp_path)
    now = datetime.now(timezone.utc)
    _insert_video_with_date(tmp_path, "Old Video", "old.mp4", now - timedelta(days=10))

    response = client.get("/api/videos")
    assert response.status_code == 200
    data = response.json()
    assert data[0]["media_status"] == "detected_video"
    assert data[0]["compatibility_status"] is not None


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


def test_scan_reconciles_stale_hls_variants_when_files_missing(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    root = tmp_path / "videos"
    root.mkdir(parents=True)
    source = root / "stale.mp4"
    source.write_bytes(b"x" * 2_000_000)
    stat = source.stat()

    from app.database import SessionLocal
    from app.models import Video, VideoVariant

    db = SessionLocal()
    _ensure_root(db, tmp_path)
    video = Video(
        title="stale",
        filename="stale.mp4",
        relative_path="stale.mp4",
        absolute_path=str(source),
        extension=".mp4",
        size=stat.st_size,
        modified_ts=stat.st_mtime,
        duration=10.0,
        width=1920,
        height=1080,
        video_codec="h264",
        audio_codec="aac",
        folder_path="",
        media_status="detected_video",
        probe_status="success",
        compatibility_status="direct_play",
        compatibility_reason="ok",
        indexed_at=datetime.now(timezone.utc),
    )
    db.add(video)
    db.commit()
    db.refresh(video)

    db.add(VideoVariant(video_id=video.id, variant_type="hls_master", status="completed", quality_label="master"))
    db.add(VideoVariant(video_id=video.id, variant_type="hls_480p", status="completed", quality_label="480p"))
    db.commit()

    scan_video_library(db, _build_settings(tmp_path))

    completed_hls_variants = (
        db.query(VideoVariant)
        .filter(VideoVariant.video_id == video.id)
        .filter(VideoVariant.variant_type.in_(["hls_master", "hls_480p"]))
        .filter(VideoVariant.status == "completed")
        .count()
    )
    db.close()

    assert completed_hls_variants == 0


def test_scanner_stops_when_cancellation_requested(tmp_path: Path, monkeypatch) -> None:
    setup_test_db(tmp_path)
    root = tmp_path / "videos"
    root.mkdir(parents=True)
    for index in range(5):
        (root / f"v{index}.mp4").write_bytes(b"0" * 2_000_000)

    from app.scan_status import is_cancellation_requested, request_scan_cancellation, start_scan

    def fake_probe(_p):
        if not is_cancellation_requested():
            request_scan_cancellation()
        time.sleep(0.01)
        return ProbeResult(success=True, has_video_stream=True, duration=10.0, width=1280, height=720, video_codec="h264", audio_codec="aac", container_format="mp4")

    monkeypatch.setattr("app.scanner.probe_video", fake_probe)
    monkeypatch.setattr("app.scanner.ensure_thumbnail", lambda *args, **kwargs: None)

    from app.database import SessionLocal

    db = SessionLocal()
    _ensure_root(db, tmp_path)
    start_scan()
    result = scan_video_library(db, _build_settings(tmp_path))
    db.close()

    assert result.cancelled is True
    assert result.scanned_files < 5


def test_cancelled_scan_does_not_run_missing_cleanup(tmp_path: Path, monkeypatch) -> None:
    setup_test_db(tmp_path)
    root = tmp_path / "videos"
    root.mkdir(parents=True)
    existing = root / "exists.mp4"
    existing.write_bytes(b"0" * 2_000_000)

    from app.database import SessionLocal
    from app.models import Video
    from app.scan_status import request_scan_cancellation, start_scan

    db = SessionLocal()
    _ensure_root(db, tmp_path)
    stale = Video(
        title="missing",
        filename="missing.mp4",
        relative_path="missing.mp4",
        absolute_path=str(root / "missing.mp4"),
        extension=".mp4",
        size=1,
        modified_ts=1.0,
        duration=1.0,
        width=640,
        height=360,
        video_codec="h264",
        audio_codec="aac",
        folder_path="",
        media_status="detected_video",
        probe_status="success",
        compatibility_status="direct_play",
        compatibility_reason="ok",
        indexed_at=datetime.now(timezone.utc),
    )
    db.add(stale)
    db.commit()

    def fake_probe(_p):
        request_scan_cancellation()
        return ProbeResult(success=True, has_video_stream=True, duration=10.0, width=1280, height=720, video_codec="h264", audio_codec="aac", container_format="mp4")

    monkeypatch.setattr("app.scanner.probe_video", fake_probe)
    monkeypatch.setattr("app.scanner.ensure_thumbnail", lambda *args, **kwargs: None)

    start_scan()
    result = scan_video_library(db, _build_settings(tmp_path))
    still_exists = db.query(Video).filter(Video.relative_path == "missing.mp4").first()
    db.close()

    assert result.cancelled is True
    assert result.removed_missing == 0
    assert still_exists is not None


def test_indexed_video_is_visible_before_scan_completion(tmp_path: Path, monkeypatch) -> None:
    setup_test_db(tmp_path)
    root = tmp_path / "videos"
    root.mkdir(parents=True)
    (root / "a.mp4").write_bytes(b"0" * 2_000_000)
    (root / "b.mp4").write_bytes(b"0" * 2_000_000)

    from app.database import SessionLocal
    from app.scan_status import start_scan

    second_probe_started = threading.Event()
    release_second_probe = threading.Event()

    def fake_probe(path: Path):
        if path.name == "b.mp4":
            second_probe_started.set()
            release_second_probe.wait(timeout=2)
        return ProbeResult(
            success=True,
            has_video_stream=True,
            duration=10.0,
            width=1280,
            height=720,
            video_codec="h264",
            audio_codec="aac",
            container_format="mp4",
        )

    monkeypatch.setattr("app.scanner.probe_video", fake_probe)
    monkeypatch.setattr("app.scanner.ensure_thumbnail", lambda *args, **kwargs: None)

    start_scan()

    def run_scan_in_thread() -> None:
        db = SessionLocal()
        try:
            _ensure_root(db, tmp_path)
            scan_video_library(db, _build_settings(tmp_path))
        finally:
            db.close()

    scan_thread = threading.Thread(target=run_scan_in_thread)
    scan_thread.start()

    assert second_probe_started.wait(timeout=2)

    client = make_client(tmp_path)
    response = client.get("/api/videos")
    assert response.status_code == 200
    filenames = {item["filename"] for item in response.json()}
    assert "a.mp4" in filenames

    release_second_probe.set()
    scan_thread.join(timeout=3)
    assert not scan_thread.is_alive()


