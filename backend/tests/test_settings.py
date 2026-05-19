"""Tests for Phase 2.5 – configurable Media Sources / Library Roots."""
import json
from pathlib import Path

import pytest

from tests.conftest import make_client, setup_test_db


def _make_settings(tmp_path: Path, *, excluded: str = "", allowed_bases: str = ""):
    """Return override envvars for settings tests."""
    import os
    if excluded:
        os.environ["EXCLUDED_EXTENSIONS"] = excluded
    else:
        os.environ.pop("EXCLUDED_EXTENSIONS", None)
    if allowed_bases is not None:
        os.environ["ALLOWED_MEDIA_ROOT_BASES"] = allowed_bases
    from app.config import get_settings
    get_settings.cache_clear()
    return get_settings()


def _add_root(db, path: Path, name: str = "Test", enabled: bool = True, scan_priority: int = 100):
    """Helper: manually insert a LibraryRoot so scanner tests don't depend on bootstrap."""
    from app.models import LibraryRoot
    root = LibraryRoot(
        name=name,
        path=str(path),
        media_type="video",
        enabled=enabled,
        recursive=True,
        scan_priority=scan_priority,
    )
    db.add(root)
    db.commit()
    db.refresh(root)
    return root


# ── First-startup behaviour (no auto-create of Default /media) ────────────


def test_first_startup_no_default_source_created(tmp_path: Path) -> None:
    """On first startup with empty DB, no Default source is auto-created."""
    import os
    setup_test_db(tmp_path)
    os.environ.pop("MEDIA_LIBRARY_ROOTS", None)
    os.environ.pop("MEDIA_LIBRARY_ROOTS_JSON", None)
    from app.config import get_settings
    get_settings.cache_clear()

    from app.database import SessionLocal
    from app.models import LibraryRoot
    from app.scanner import initialize_library_roots

    db = SessionLocal()
    try:
        assert db.query(LibraryRoot).count() == 0
        initialize_library_roots(db, get_settings())
        assert db.query(LibraryRoot).count() == 0, "No default source should be auto-created"
    finally:
        db.close()


def test_list_media_sources_empty_on_first_startup(tmp_path: Path) -> None:
    """GET /api/settings/media-sources returns empty list on first startup."""
    client = make_client(tmp_path)
    resp = client.get("/api/settings/media-sources")
    assert resp.status_code == 200
    assert resp.json() == []


def test_invalid_default_media_source_removed_by_migration(tmp_path: Path) -> None:
    """Existing 'Default' source pointing to VIDEO_LIBRARY_PATH is removed on startup."""
    setup_test_db(tmp_path)
    video_dir = tmp_path / "videos"
    video_dir.mkdir(parents=True)

    from app.database import SessionLocal
    from app.models import LibraryRoot
    from app.scanner import initialize_library_roots
    from app.config import get_settings

    db = SessionLocal()
    try:
        # Simulate old behaviour: manually insert the invalid default record
        stale = LibraryRoot(
            name="Default",
            path=str(video_dir),  # matches VIDEO_LIBRARY_PATH from conftest
            media_type="video",
            enabled=True,
            recursive=True,
            scan_priority=100,
        )
        db.add(stale)
        db.commit()
        assert db.query(LibraryRoot).count() == 1

        initialize_library_roots(db, get_settings())
        # The stale default pointing at VIDEO_LIBRARY_PATH must be removed
        assert db.query(LibraryRoot).count() == 0
    finally:
        db.close()


def test_adding_media_root_rejected(tmp_path: Path) -> None:
    """POST /api/settings/media-sources rejects adding the VIDEO_LIBRARY_PATH base."""
    setup_test_db(tmp_path)
    video_dir = tmp_path / "videos"
    video_dir.mkdir(parents=True)

    client = make_client(tmp_path)
    resp = client.post(
        "/api/settings/media-sources",
        json={"name": "Root", "path": str(video_dir)},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "root_source_not_allowed"


def test_adding_subfolder_works(tmp_path: Path) -> None:
    """POST /api/settings/media-sources accepts a valid subfolder path."""
    setup_test_db(tmp_path)
    video_dir = tmp_path / "videos"
    movies_dir = video_dir / "Movies"
    movies_dir.mkdir(parents=True)

    client = make_client(tmp_path)
    resp = client.post(
        "/api/settings/media-sources",
        json={"name": "Movies", "path": str(movies_dir)},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["name"] == "Movies"
    assert "relative_path" in data
    assert "display_path" in data


def test_scan_with_no_sources_returns_no_sources(tmp_path: Path) -> None:
    """POST /api/scan returns no_sources when no media sources are configured."""
    from app.scan_status import _lock, _state

    client = make_client(tmp_path)
    with _lock:
        _state.status = "idle"
        _state.cancellation_requested = False
        _state.current_file = None
        _state.current_root = None
        _state.message = None
    resp = client.post("/api/scan")
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "no_sources"
    assert "media sources" in data["message"].lower()


def test_scan_with_no_sources_never_scans_media_root(tmp_path: Path, monkeypatch) -> None:
    """Scanner never processes files when no sources are configured."""
    setup_test_db(tmp_path)
    video_dir = tmp_path / "videos"
    video_dir.mkdir(parents=True)
    (video_dir / "test.mp4").write_bytes(b"0" * 2_000_000)

    scanned_paths = []

    def fake_probe(p):
        scanned_paths.append(p)
        from app.media_probe import ProbeResult
        return ProbeResult(success=False, error="should not be called")

    monkeypatch.setattr("app.scanner.probe_video", fake_probe)

    from app.database import SessionLocal
    from app.scanner import scan_video_library
    from app.config import get_settings

    db = SessionLocal()
    result = scan_video_library(db, get_settings())
    db.close()

    assert len(scanned_paths) == 0
    assert result.scanned_files == 0
    assert "no media sources" in (result.message or "").lower()


def test_docker_video_player_path_blocked(tmp_path: Path) -> None:
    """Paths under the docker infrastructure directory are rejected as media sources."""
    setup_test_db(tmp_path)
    video_dir = tmp_path / "videos"
    blocked_dir = video_dir / "docker" / "video-player" / "thumbnails"
    blocked_dir.mkdir(parents=True)

    client = make_client(tmp_path)
    resp = client.post(
        "/api/settings/media-sources",
        json={"name": "Bad", "path": str(blocked_dir)},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "runtime_path_blocked"


def test_browse_endpoint_returns_directories(tmp_path: Path) -> None:
    """GET /api/settings/media-sources/browse returns child directories."""
    setup_test_db(tmp_path)
    video_dir = tmp_path / "videos"
    (video_dir / "Movies").mkdir(parents=True)
    (video_dir / "GoPro").mkdir(parents=True)

    client = make_client(tmp_path)
    resp = client.get("/api/settings/media-sources/browse")
    assert resp.status_code == 200
    data = resp.json()
    names = [item["name"] for item in data]
    assert "Movies" in names
    assert "GoPro" in names
    for item in data:
        assert "relative_path" in item
        assert "display_path" in item
        assert item["is_directory"] is True


def test_browse_does_not_escape_media_root(tmp_path: Path) -> None:
    """Browse endpoint ignores traversal attempts."""
    client = make_client(tmp_path)
    resp = client.get("/api/settings/media-sources/browse?relative_path=../../etc")
    # Should either return empty or the root listing, never escape
    assert resp.status_code == 200


def test_validate_root_source_rejected(tmp_path: Path) -> None:
    """Validating the media root path returns root_source_not_allowed."""
    setup_test_db(tmp_path)
    video_dir = tmp_path / "videos"
    video_dir.mkdir(parents=True)

    client = make_client(tmp_path)
    resp = client.post(
        "/api/settings/media-sources/validate",
        json={"path": str(video_dir)},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is False
    assert data["code"] == "root_source_not_allowed"


# ── Bootstrap from environment variables ──────────────────────────────────


def test_bootstrap_from_media_library_roots_env(tmp_path: Path) -> None:
    """MEDIA_LIBRARY_ROOTS env initialises multiple roots."""
    import os
    setup_test_db(tmp_path)

    root_a = tmp_path / "videos" / "gopro"
    root_b = tmp_path / "videos" / "family"
    root_a.mkdir(parents=True)
    root_b.mkdir(parents=True)

    os.environ["MEDIA_LIBRARY_ROOTS"] = f"{root_a},{root_b}"
    from app.config import get_settings
    get_settings.cache_clear()

    from app.database import SessionLocal
    from app.models import LibraryRoot
    from app.scanner import initialize_library_roots

    db = SessionLocal()
    try:
        initialize_library_roots(db, get_settings())
        count = db.query(LibraryRoot).count()
        assert count == 2
        paths = {r.path for r in db.query(LibraryRoot).all()}
        assert str(root_a) in paths
        assert str(root_b) in paths
    finally:
        db.close()
        os.environ.pop("MEDIA_LIBRARY_ROOTS", None)
        get_settings.cache_clear()


def test_bootstrap_from_media_library_roots_json_env(tmp_path: Path) -> None:
    """MEDIA_LIBRARY_ROOTS_JSON initialises named roots."""
    import os
    setup_test_db(tmp_path)

    root_a = tmp_path / "videos" / "movies"
    root_a.mkdir(parents=True)

    config = json.dumps([{"name": "Movies", "path": str(root_a), "scan_priority": 50}])
    os.environ["MEDIA_LIBRARY_ROOTS_JSON"] = config
    from app.config import get_settings
    get_settings.cache_clear()

    from app.database import SessionLocal
    from app.models import LibraryRoot
    from app.scanner import initialize_library_roots

    db = SessionLocal()
    try:
        initialize_library_roots(db, get_settings())
        root = db.query(LibraryRoot).first()
        assert root is not None
        assert root.name == "Movies"
        assert root.path == str(root_a)
        assert root.scan_priority == 50
    finally:
        db.close()
        os.environ.pop("MEDIA_LIBRARY_ROOTS_JSON", None)
        get_settings.cache_clear()


def test_initialize_library_roots_is_idempotent(tmp_path: Path) -> None:
    """initialize_library_roots is idempotent."""
    import os
    setup_test_db(tmp_path)
    root_a = tmp_path / "videos" / "gopro"
    root_a.mkdir(parents=True)
    os.environ["MEDIA_LIBRARY_ROOTS"] = str(root_a)
    from app.config import get_settings
    get_settings.cache_clear()

    from app.database import SessionLocal
    from app.models import LibraryRoot
    from app.scanner import initialize_library_roots

    db = SessionLocal()
    try:
        initialize_library_roots(db, get_settings())
        initialize_library_roots(db, get_settings())
        assert db.query(LibraryRoot).count() == 1
    finally:
        db.close()
        os.environ.pop("MEDIA_LIBRARY_ROOTS", None)
        get_settings.cache_clear()


# ── Media Sources API ──────────────────────────────────────────────────────


def test_list_media_sources_after_create(tmp_path: Path) -> None:
    """Created sources appear in the list."""
    setup_test_db(tmp_path)
    root_path = tmp_path / "videos" / "list_root"
    root_path.mkdir(parents=True)

    client = make_client(tmp_path)
    client.post(
        "/api/settings/media-sources",
        json={"name": "Listed Root", "path": str(root_path)},
    )

    resp = client.get("/api/settings/media-sources")
    assert resp.status_code == 200
    data = resp.json()
    names = [s["name"] for s in data]
    assert "Listed Root" in names


def test_create_media_source(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    root_path = tmp_path / "videos" / "new_root"
    root_path.mkdir(parents=True)

    client = make_client(tmp_path)
    resp = client.post(
        "/api/settings/media-sources",
        json={
            "name": "Test Root",
            "path": str(root_path),
            "media_type": "video",
            "enabled": True,
            "recursive": True,
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["name"] == "Test Root"
    assert data["path"] == str(root_path)
    assert data["enabled"] is True
    assert data["recursive"] is True
    assert data["media_type"] == "video"
    assert "id" in data


def test_duplicate_path_rejected(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    root_path = tmp_path / "videos" / "dup_root"
    root_path.mkdir(parents=True)

    client = make_client(tmp_path)
    resp1 = client.post(
        "/api/settings/media-sources",
        json={"name": "Root A", "path": str(root_path)},
    )
    assert resp1.status_code == 201

    resp2 = client.post(
        "/api/settings/media-sources",
        json={"name": "Root B", "path": str(root_path)},
    )
    assert resp2.status_code == 409
    assert resp2.json()["detail"]["code"] == "duplicate_path"


def test_get_media_source(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    root_path = tmp_path / "videos" / "get_test"
    root_path.mkdir(parents=True)

    client = make_client(tmp_path)
    create_resp = client.post(
        "/api/settings/media-sources",
        json={"name": "Get Test", "path": str(root_path)},
    )
    source_id = create_resp.json()["id"]

    resp = client.get(f"/api/settings/media-sources/{source_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Get Test"


def test_update_media_source(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    root_path = tmp_path / "videos" / "update_test"
    root_path.mkdir(parents=True)

    client = make_client(tmp_path)
    create_resp = client.post(
        "/api/settings/media-sources",
        json={"name": "Old Name", "path": str(root_path)},
    )
    source_id = create_resp.json()["id"]

    resp = client.put(
        f"/api/settings/media-sources/{source_id}",
        json={"name": "New Name", "enabled": False},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "New Name"
    assert data["enabled"] is False


def test_delete_media_source(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    root_path = tmp_path / "videos" / "delete_test"
    root_path.mkdir(parents=True)

    client = make_client(tmp_path)
    create_resp = client.post(
        "/api/settings/media-sources",
        json={"name": "To Delete", "path": str(root_path)},
    )
    source_id = create_resp.json()["id"]

    del_resp = client.delete(f"/api/settings/media-sources/{source_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["deleted"] is True

    get_resp = client.get(f"/api/settings/media-sources/{source_id}")
    assert get_resp.status_code == 404


# ── Path validation ────────────────────────────────────────────────────────


def test_validate_path_valid(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    valid_dir = tmp_path / "videos" / "valid_media"
    valid_dir.mkdir(parents=True)

    client = make_client(tmp_path)
    resp = client.post(
        "/api/settings/media-sources/validate",
        json={"path": str(valid_dir)},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is True


def test_validate_path_not_found(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    resp = client.post(
        "/api/settings/media-sources/validate",
        json={"path": str(tmp_path / "does_not_exist")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is False
    assert data["code"] == "path_not_found"


def test_validate_path_not_directory(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    file_path = tmp_path / "a_file.txt"
    file_path.write_text("hello")

    resp = client.post(
        "/api/settings/media-sources/validate",
        json={"path": str(file_path)},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is False
    assert data["code"] == "not_directory"


def test_validate_path_outside_allowed_bases(tmp_path: Path) -> None:
    import os
    setup_test_db(tmp_path)
    os.environ["ALLOWED_MEDIA_ROOT_BASES"] = "/restricted/allowed"
    from app.config import get_settings
    get_settings.cache_clear()

    from app.routes.settings import validate_media_source_path
    result = validate_media_source_path(str(tmp_path / "media"), get_settings())
    assert result.valid is False
    assert result.code == "outside_allowed_bases"

    os.environ.pop("ALLOWED_MEDIA_ROOT_BASES", None)
    get_settings.cache_clear()


# ── Scanner integration ────────────────────────────────────────────────────


def test_scanner_uses_enabled_roots(tmp_path: Path, monkeypatch) -> None:
    """Scanner scans explicitly configured library roots."""
    from app.media_probe import ProbeResult

    setup_test_db(tmp_path)
    root = tmp_path / "videos" / "media_root"
    root.mkdir(parents=True)
    (root / "clip.mp4").write_bytes(b"0" * 2_000_000)

    monkeypatch.setattr(
        "app.scanner.probe_video",
        lambda _p: ProbeResult(
            success=True, has_video_stream=True, duration=10.0,
            width=1920, height=1080, video_codec="h264", audio_codec="aac",
            container_format="mp4",
        ),
    )
    monkeypatch.setattr("app.scanner.ensure_thumbnail", lambda *a, **kw: None)

    from app.database import SessionLocal
    from app.models import Video, LibraryRoot
    from app.scanner import scan_video_library
    from app.config import get_settings

    db = SessionLocal()
    _add_root(db, root, name="Media Root")
    result = scan_video_library(db, get_settings())
    videos = db.query(Video).all()
    roots = db.query(LibraryRoot).all()
    db.close()

    assert result.added == 1
    assert len(videos) == 1
    assert videos[0].library_root_id is not None
    assert len(roots) == 1
    assert roots[0].last_scan_status == "completed"


def test_scanner_skips_disabled_roots(tmp_path: Path, monkeypatch) -> None:
    """Scanner does not scan disabled roots."""
    from app.media_probe import ProbeResult

    setup_test_db(tmp_path)
    enabled_root = tmp_path / "videos" / "enabled"
    enabled_root.mkdir(parents=True)
    (enabled_root / "enabled.mp4").write_bytes(b"0" * 2_000_000)

    disabled_root = tmp_path / "videos" / "disabled"
    disabled_root.mkdir(parents=True)
    (disabled_root / "disabled.mp4").write_bytes(b"0" * 2_000_000)

    from app.database import SessionLocal
    from app.models import Video
    from app.scanner import scan_video_library
    from app.config import get_settings

    db = SessionLocal()
    _add_root(db, enabled_root, name="Enabled", enabled=True)
    _add_root(db, disabled_root, name="Disabled", enabled=False, scan_priority=200)

    monkeypatch.setattr(
        "app.scanner.probe_video",
        lambda _p: ProbeResult(
            success=True, has_video_stream=True, duration=10.0,
            width=1920, height=1080, video_codec="h264", audio_codec="aac",
            container_format="mp4",
        ),
    )
    monkeypatch.setattr("app.scanner.ensure_thumbnail", lambda *a, **kw: None)

    result = scan_video_library(db, get_settings())

    videos = db.query(Video).all()
    db.close()

    assert result.added == 1
    filenames = {v.filename for v in videos}
    assert "enabled.mp4" in filenames
    assert "disabled.mp4" not in filenames


def test_scanner_stores_library_root_id(tmp_path: Path, monkeypatch) -> None:
    """library_root_id is stored on indexed videos."""
    from app.media_probe import ProbeResult

    setup_test_db(tmp_path)
    root = tmp_path / "videos" / "test_root"
    root.mkdir(parents=True)
    (root / "test.mp4").write_bytes(b"0" * 2_000_000)

    monkeypatch.setattr(
        "app.scanner.probe_video",
        lambda _p: ProbeResult(
            success=True, has_video_stream=True, duration=5.0,
            width=1280, height=720, video_codec="h264", audio_codec="aac",
            container_format="mp4",
        ),
    )
    monkeypatch.setattr("app.scanner.ensure_thumbnail", lambda *a, **kw: None)

    from app.database import SessionLocal
    from app.models import Video, LibraryRoot
    from app.scanner import scan_video_library
    from app.config import get_settings

    db = SessionLocal()
    _add_root(db, root, name="Test Root")
    scan_video_library(db, get_settings())
    video = db.query(Video).first()
    root_record = db.query(LibraryRoot).first()
    db.close()

    assert video is not None
    assert video.library_root_id == root_record.id


def test_scanner_allows_same_relative_path_in_multiple_roots(tmp_path: Path, monkeypatch) -> None:
    """Videos from different roots may share the same relative_path."""
    import os

    from app.media_probe import ProbeResult

    setup_test_db(tmp_path)
    root_a = tmp_path / "videos" / "root_a"
    root_b = tmp_path / "videos" / "root_b"
    (root_a / "shared").mkdir(parents=True)
    (root_b / "shared").mkdir(parents=True)
    (root_a / "shared" / "movie.mp4").write_bytes(b"0" * 2_000_000)
    (root_b / "shared" / "movie.mp4").write_bytes(b"1" * 2_000_000)

    os.environ["MEDIA_LIBRARY_ROOTS"] = f"{root_a},{root_b}"
    from app.config import get_settings
    get_settings.cache_clear()

    monkeypatch.setattr(
        "app.scanner.probe_video",
        lambda _p: ProbeResult(
            success=True, has_video_stream=True, duration=5.0,
            width=1280, height=720, video_codec="h264", audio_codec="aac",
            container_format="mp4",
        ),
    )
    monkeypatch.setattr("app.scanner.ensure_thumbnail", lambda *a, **kw: None)

    from app.database import SessionLocal
    from app.models import Video
    from app.scanner import scan_video_library, initialize_library_roots

    db = SessionLocal()
    try:
        initialize_library_roots(db, get_settings())
        result = scan_video_library(db, get_settings())
        videos = db.query(Video).order_by(Video.absolute_path.asc()).all()
        assert result.added == 2
        assert len(videos) == 2
        assert {video.relative_path for video in videos} == {"shared/movie.mp4"}
        assert len({video.library_root_id for video in videos}) == 2
    finally:
        db.close()
        os.environ.pop("MEDIA_LIBRARY_ROOTS", None)
        get_settings.cache_clear()


def test_download_uses_video_absolute_path_for_secondary_root(tmp_path: Path) -> None:
    """Download endpoint must resolve files using the video's indexed absolute path."""
    setup_test_db(tmp_path)
    client = make_client(tmp_path)

    secondary_root = tmp_path / "videos" / "secondary"
    secondary_root.mkdir(parents=True)
    source_file = secondary_root / "secondary.mp4"
    source_file.write_bytes(b"secondary-video")
    stat = source_file.stat()

    from app.database import SessionLocal
    from app.models import LibraryRoot, Video

    db = SessionLocal()
    try:
        root = LibraryRoot(
            name="Secondary",
            path=str(secondary_root),
            media_type="video",
            enabled=True,
            recursive=True,
            scan_priority=10,
        )
        db.add(root)
        db.commit()
        db.refresh(root)

        video = Video(
            title="Secondary Video",
            filename="secondary.mp4",
            relative_path="secondary.mp4",
            absolute_path=str(source_file),
            extension=".mp4",
            size=stat.st_size,
            modified_ts=stat.st_mtime,
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
            library_root_id=root.id,
        )
        db.add(video)
        db.commit()
        db.refresh(video)
        video_id = video.id
    finally:
        db.close()

    response = client.get(f"/api/videos/{video_id}/download")
    assert response.status_code == 200
    assert response.content == b"secondary-video"


def test_audio_extensions_skipped_quickly(tmp_path: Path, monkeypatch) -> None:
    """Well-known audio extensions are skipped without probing."""
    setup_test_db(tmp_path)
    root = tmp_path / "videos" / "audio_test"
    root.mkdir(parents=True)

    for ext in [".mp3", ".flac", ".wav", ".m4a", ".aac"]:
        (root / f"audio{ext}").write_bytes(b"0" * 500_000)

    probe_called = []
    from app.media_probe import ProbeResult

    def _probe(p):
        probe_called.append(p)
        return ProbeResult(success=False, error="should not be called")

    monkeypatch.setattr("app.scanner.probe_video", _probe)

    from app.database import SessionLocal
    from app.scanner import scan_video_library
    from app.config import get_settings

    db = SessionLocal()
    _add_root(db, root, name="Audio Test")
    result = scan_video_library(db, get_settings())
    db.close()

    assert len(probe_called) == 0, "Audio files should not be probed"
    assert result.ignored_excluded == 5


def test_image_extensions_skipped_quickly(tmp_path: Path, monkeypatch) -> None:
    """Well-known image extensions are skipped without probing."""
    setup_test_db(tmp_path)
    root = tmp_path / "videos" / "image_test"
    root.mkdir(parents=True)

    for ext in [".jpg", ".jpeg", ".png", ".heic", ".webp"]:
        (root / f"photo{ext}").write_bytes(b"0" * 500_000)

    probe_called = []
    from app.media_probe import ProbeResult

    def _probe(p):
        probe_called.append(p)
        return ProbeResult(success=False, error="should not be called")

    monkeypatch.setattr("app.scanner.probe_video", _probe)

    from app.database import SessionLocal
    from app.scanner import scan_video_library
    from app.config import get_settings

    db = SessionLocal()
    _add_root(db, root, name="Image Test")
    result = scan_video_library(db, get_settings())
    db.close()

    assert len(probe_called) == 0, "Image files should not be probed"
    assert result.ignored_excluded == 5



def _make_settings(tmp_path: Path, *, excluded: str = "", allowed_bases: str = ""):
    """Return override envvars for settings tests."""
    import os
    if excluded:
        os.environ["EXCLUDED_EXTENSIONS"] = excluded
    else:
        os.environ.pop("EXCLUDED_EXTENSIONS", None)
    if allowed_bases is not None:
        os.environ["ALLOWED_MEDIA_ROOT_BASES"] = allowed_bases
    from app.config import get_settings
    get_settings.cache_clear()
    return get_settings()

