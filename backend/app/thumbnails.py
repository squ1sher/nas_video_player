import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def build_thumbnail_name(relative_path: str) -> str:
    safe_name = relative_path.replace("/", "__").replace("\\", "__")
    return f"{safe_name}.jpg"


def ensure_thumbnail(video_path: Path, thumbnails_dir: Path, relative_path: str) -> Path | None:
    thumbnails_dir.mkdir(parents=True, exist_ok=True)
    thumb_file = thumbnails_dir / build_thumbnail_name(relative_path)
    if thumb_file.exists():
        return thumb_file

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
        return thumb_file
    except subprocess.CalledProcessError as exc:
        logger.error("Thumbnail generation failed for %s: %s", video_path, exc.stderr or exc)
        return None

