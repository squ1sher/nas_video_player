from pathlib import Path

from app.config import Settings


def test_ensure_runtime_dirs_creates_expected_paths(tmp_path: Path) -> None:
    settings = Settings(
        VIDEO_LIBRARY_PATH=str(tmp_path / "media"),
        DATABASE_PATH=str(tmp_path / "data" / "app.db"),
        THUMBNAILS_PATH=str(tmp_path / "thumbnails"),
        CACHE_PATH=str(tmp_path / "cache"),
        HLS_OUTPUT_PATH=str(tmp_path / "cache" / "hls"),
        LOGS_PATH=str(tmp_path / "logs"),
    )

    settings.ensure_runtime_dirs()

    assert (tmp_path / "data").is_dir()
    assert (tmp_path / "thumbnails").is_dir()
    assert (tmp_path / "cache").is_dir()
    assert (tmp_path / "cache" / "hls").is_dir()
    assert (tmp_path / "logs").is_dir()

