import mimetypes
from pathlib import Path

VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".mkv", ".avi", ".webm", ".mpg", ".mpeg", ".360"}
PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".tif", ".tiff"}
RAW_PHOTO_EXTENSIONS = {".arw", ".cr2", ".cr3", ".nef", ".dng", ".raf", ".rw2"}
IMAGE_EXTENSIONS = PHOTO_EXTENSIONS | RAW_PHOTO_EXTENSIONS
MIME_OVERRIDES = {
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
    ".avi": "video/x-msvideo",
    ".mpg": "video/mpeg",
    ".mpeg": "video/mpeg",
    ".360": "application/octet-stream",
}


def is_video_file(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTENSIONS


def is_photo_file(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def is_raw_photo_file(path: Path) -> bool:
    return path.suffix.lower() in RAW_PHOTO_EXTENSIONS


def safe_resolve_under_root(root: Path, relative_path: str) -> Path:
    base = root.resolve()
    candidate = (base / relative_path).resolve()
    if not candidate.is_file() or base not in candidate.parents and candidate != base:
        raise ValueError("Requested path is outside of the video library")
    return candidate


def guess_mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in MIME_OVERRIDES:
        return MIME_OVERRIDES[suffix]
    return mimetypes.guess_type(str(path))[0] or "application/octet-stream"

