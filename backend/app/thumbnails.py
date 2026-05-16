import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ThumbnailResult:
    path: Path | None
    error: str | None = None


def build_thumbnail_name(relative_path: str) -> str:
    safe_name = relative_path.replace("/", "__").replace("\\", "__")
    return f"{safe_name}.jpg"


def generate_thumbnail(
    video_path: Path,
    thumbnails_dir: Path,
    relative_path: str,
    *,
    force: bool = False,
) -> ThumbnailResult:
    thumbnails_dir.mkdir(parents=True, exist_ok=True)
    thumb_file = thumbnails_dir / build_thumbnail_name(relative_path)
    if thumb_file.exists() and not force:
        return ThumbnailResult(path=thumb_file)

    if force and thumb_file.exists():
        try:
            thumb_file.unlink()
        except OSError as exc:
            logger.warning("Failed to remove old thumbnail for %s: %s", video_path, exc)

    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        "00:00:01",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(thumb_file),
    ]

    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        return ThumbnailResult(path=thumb_file)
    except subprocess.CalledProcessError as exc:
        error = (exc.stderr or str(exc)).strip()
        logger.error("Thumbnail generation failed for %s: %s", video_path, error)
        return ThumbnailResult(path=None, error=error)


def ensure_thumbnail(video_path: Path, thumbnails_dir: Path, relative_path: str) -> Path | None:
    return generate_thumbnail(video_path, thumbnails_dir, relative_path).path

