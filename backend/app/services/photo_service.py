from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import Photo
from app.utils.files import is_raw_photo_file

try:
    from PIL import Image, ImageOps, UnidentifiedImageError
except Exception:  # noqa: BLE001
    Image = None  # type: ignore[assignment]
    ImageOps = None  # type: ignore[assignment]

    class UnidentifiedImageError(Exception):
        pass

try:
    import rawpy
except ImportError:  # noqa: BLE001
    rawpy = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

PHOTO_THUMBNAIL_NAMESPACE = "photos"
PHOTO_THUMBNAIL_SIZE = 480
PHOTO_PREVIEW_SIZE = 2048


@dataclass
class PhotoThumbnailResult:
    path: Path | None
    error: str | None = None


@dataclass
class PhotoMetadata:
    width: int | None = None
    height: int | None = None
    orientation: int | None = None
    camera_make: str | None = None
    camera_model: str | None = None
    lens_model: str | None = None
    iso: int | None = None
    exposure_time: str | None = None
    aperture: str | None = None
    focal_length: str | None = None
    captured_at: datetime | None = None
    date_source: str | None = None
    raw_format: bool = False


def _parse_exif_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.strptime(value.strip(), "%Y:%m:%d %H:%M:%S")
        return parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _format_rational(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, tuple) and len(value) == 2:
        numerator, denominator = value
        try:
            denominator = float(denominator)
            if denominator == 0:
                return None
            return f"{float(numerator) / denominator:g}"
        except (TypeError, ValueError, ZeroDivisionError):
            return None
    return str(value)


def _pick_first_datetime(exif: object) -> tuple[datetime | None, str | None]:
    if not exif:
        return None, None
    for key, label in ((36867, "exif_original"), (36868, "exif_create"), (306, "exif_create")):
        value = None
        try:
            value = exif.get(key) if hasattr(exif, "get") else exif[key]  # type: ignore[index]
        except Exception:  # noqa: BLE001
            value = None
        parsed = _parse_exif_datetime(value)
        if parsed:
            return parsed, label
    return None, None


def _stat_to_datetime(timestamp: float | None) -> datetime | None:
    if timestamp is None:
        return None
    try:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def extract_photo_metadata(file_path: Path, stat_mtime: float, stat_birthtime: float | None = None) -> PhotoMetadata:
    raw_format = is_raw_photo_file(file_path)
    if raw_format:
        captured_at = _stat_to_datetime(stat_birthtime) or _stat_to_datetime(stat_mtime)
        return PhotoMetadata(
            captured_at=captured_at,
            date_source="file_created" if stat_birthtime is not None else "file_modified",
            raw_format=True,
        )

    if Image is None:
        file_created_at = _stat_to_datetime(stat_birthtime)
        file_modified_at = _stat_to_datetime(stat_mtime)
        captured_at = file_created_at or file_modified_at
        return PhotoMetadata(
            captured_at=captured_at,
            date_source="file_created" if file_created_at else ("file_modified" if file_modified_at else "unknown"),
            raw_format=False,
        )

    try:
        with Image.open(file_path) as image:
            exif = image.getexif()
            exif_datetime, date_source = _pick_first_datetime(exif)
            file_created_at = _stat_to_datetime(stat_birthtime)
            file_modified_at = _stat_to_datetime(stat_mtime)

            captured_at = exif_datetime or file_created_at or file_modified_at
            if captured_at is exif_datetime:
                selected_source = date_source or "exif_original"
            elif captured_at is file_created_at:
                selected_source = "file_created"
            elif captured_at is file_modified_at:
                selected_source = "file_modified"
            else:
                selected_source = "unknown"

            orientation = None
            try:
                orientation = int(exif.get(274)) if exif and exif.get(274) is not None else None
            except (TypeError, ValueError):
                orientation = None

            def _exif_text(tag: int) -> str | None:
                try:
                    value = exif.get(tag) if exif else None
                except Exception:  # noqa: BLE001
                    value = None
                if value in (None, ""):
                    return None
                return str(value)

            iso = None
            try:
                iso_value = exif.get(34855) if exif else None
                if iso_value is not None:
                    iso = int(iso_value)
            except (TypeError, ValueError):
                iso = None

            return PhotoMetadata(
                width=image.width,
                height=image.height,
                orientation=orientation,
                camera_make=_exif_text(271),
                camera_model=_exif_text(272),
                lens_model=_exif_text(42036),
                iso=iso,
                exposure_time=_format_rational(exif.get(33434) if exif else None),
                aperture=_format_rational(exif.get(33437) if exif else None),
                focal_length=_format_rational(exif.get(37386) if exif else None),
                captured_at=captured_at,
                date_source=selected_source,
                raw_format=False,
            )
    except UnidentifiedImageError:
        logger.info("Unsupported image format for metadata extraction: %s", file_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to extract photo metadata for %s: %s", file_path, exc)

    file_created_at = _stat_to_datetime(stat_birthtime)
    file_modified_at = _stat_to_datetime(stat_mtime)
    captured_at = file_created_at or file_modified_at
    return PhotoMetadata(
        captured_at=captured_at,
        date_source="file_created" if file_created_at else ("file_modified" if file_modified_at else "unknown"),
        raw_format=is_raw_photo_file(file_path),
    )


def build_photo_thumbnail_relative_path(photo_id: int) -> str:
    return f"{PHOTO_THUMBNAIL_NAMESPACE}/{photo_id}.jpg"


def build_photo_preview_relative_path(photo_id: int) -> str:
    return f"{PHOTO_THUMBNAIL_NAMESPACE}/{photo_id}_preview.jpg"


def _save_jpeg(image: "Image.Image", target_path: Path, max_edge: int) -> None:
    """Resize (in place copy) to fit max_edge and save as JPEG."""
    image = ImageOps.exif_transpose(image)
    if image.mode != "RGB":
        image = image.convert("RGB")
    image.thumbnail((max_edge, max_edge))
    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target_path.with_name(f".{target_path.name}.tmp")
    try:
        image.save(tmp_path, format="JPEG", quality=85, optimize=True)
        tmp_path.replace(target_path)
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass


def generate_photo_thumbnail(photo_path: Path, thumbnails_dir: Path, photo_id: int) -> PhotoThumbnailResult:
    if Image is None or ImageOps is None:
        return PhotoThumbnailResult(path=None, error="Pillow is unavailable in this runtime")

    out_dir = thumbnails_dir / PHOTO_THUMBNAIL_NAMESPACE
    out_dir.mkdir(parents=True, exist_ok=True)
    thumb_path = out_dir / f"{photo_id}.jpg"

    try:
        with Image.open(photo_path) as image:
            _save_jpeg(image, thumb_path, PHOTO_THUMBNAIL_SIZE)
        return PhotoThumbnailResult(path=thumb_path)
    except UnidentifiedImageError as exc:
        return PhotoThumbnailResult(path=None, error=f"Unsupported image format: {exc}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to generate photo thumbnail for %s: %s", photo_path, exc)
        return PhotoThumbnailResult(path=None, error=str(exc))


def generate_photo_preview(photo_path: Path, thumbnails_dir: Path, photo_id: int) -> PhotoThumbnailResult:
    """Generate a larger JPEG preview for the viewer (standard image formats)."""
    if Image is None or ImageOps is None:
        return PhotoThumbnailResult(path=None, error="Pillow is unavailable in this runtime")

    out_dir = thumbnails_dir / PHOTO_THUMBNAIL_NAMESPACE
    out_dir.mkdir(parents=True, exist_ok=True)
    preview_path = out_dir / f"{photo_id}_preview.jpg"

    try:
        with Image.open(photo_path) as image:
            _save_jpeg(image, preview_path, PHOTO_PREVIEW_SIZE)
        return PhotoThumbnailResult(path=preview_path)
    except UnidentifiedImageError as exc:
        return PhotoThumbnailResult(path=None, error=f"Unsupported image format: {exc}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to generate photo preview for %s: %s", photo_path, exc)
        return PhotoThumbnailResult(path=None, error=str(exc))


def _load_raw_as_image(photo_path: Path) -> tuple["Image.Image | None", str | None]:
    """
    Load a RAW file into a PIL Image.

    Strategy:
      1. Extract the embedded JPEG/bitmap preview via rawpy.extract_thumb() (fast, good quality).
      2. Fall back to a half-size demosaic via rawpy.postprocess() (slower but always works).
    Returns (image, error). image is None on failure.
    """
    if rawpy is None:
        return None, "RAW preview support unavailable: rawpy is not installed"
    if Image is None:
        return None, "Pillow is unavailable in this runtime"

    import io

    try:
        with rawpy.imread(str(photo_path)) as raw:  # type: ignore[union-attr]
            # 1) Embedded thumbnail / preview
            try:
                thumb = raw.extract_thumb()
            except Exception as exc:  # noqa: BLE001 (LibRawNoThumbnailError etc.)
                logger.debug("No embedded thumbnail for %s: %s", photo_path, exc)
                thumb = None

            if thumb is not None:
                try:
                    fmt = getattr(thumb, "format", None)
                    if fmt is not None and fmt == rawpy.ThumbFormat.JPEG:  # type: ignore[union-attr]
                        image = Image.open(io.BytesIO(thumb.data))
                        image.load()
                        return image, None
                    if fmt is not None and fmt == rawpy.ThumbFormat.BITMAP:  # type: ignore[union-attr]
                        return Image.fromarray(thumb.data), None
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Failed to decode embedded RAW thumb for %s: %s", photo_path, exc)

            # 2) Demosaic fallback (half_size keeps memory/time reasonable)
            try:
                rgb_array = raw.postprocess(half_size=True, use_camera_wb=True, no_auto_bright=False)
                return Image.fromarray(rgb_array), None
            except Exception as exc:  # noqa: BLE001
                return None, f"RAW post-processing failed: {exc}"
    except Exception as exc:  # noqa: BLE001
        return None, f"RAW conversion failed: {exc}"


def generate_raw_thumbnail(photo_path: Path, thumbnails_dir: Path, photo_id: int) -> PhotoThumbnailResult:
    """Generate a grid thumbnail for a RAW photo file (ARW, CR2, NEF, etc.)."""
    if not is_raw_photo_file(photo_path):
        return PhotoThumbnailResult(path=None, error="Not a RAW file")

    image, error = _load_raw_as_image(photo_path)
    if image is None:
        return PhotoThumbnailResult(path=None, error=error or "RAW conversion failed")

    out_dir = thumbnails_dir / PHOTO_THUMBNAIL_NAMESPACE
    out_dir.mkdir(parents=True, exist_ok=True)
    thumb_path = out_dir / f"{photo_id}.jpg"
    try:
        _save_jpeg(image, thumb_path, PHOTO_THUMBNAIL_SIZE)
        logger.info("Generated RAW thumbnail for %s", photo_path)
        return PhotoThumbnailResult(path=thumb_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to write RAW thumbnail for %s: %s", photo_path, exc)
        return PhotoThumbnailResult(path=None, error=f"Failed to write thumbnail: {exc}")


def generate_raw_preview(photo_path: Path, thumbnails_dir: Path, photo_id: int) -> PhotoThumbnailResult:
    """Generate a larger JPEG preview for the viewer from a RAW file."""
    if not is_raw_photo_file(photo_path):
        return PhotoThumbnailResult(path=None, error="Not a RAW file")

    image, error = _load_raw_as_image(photo_path)
    if image is None:
        return PhotoThumbnailResult(path=None, error=error or "RAW conversion failed")

    out_dir = thumbnails_dir / PHOTO_THUMBNAIL_NAMESPACE
    out_dir.mkdir(parents=True, exist_ok=True)
    preview_path = out_dir / f"{photo_id}_preview.jpg"
    try:
        _save_jpeg(image, preview_path, PHOTO_PREVIEW_SIZE)
        return PhotoThumbnailResult(path=preview_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to write RAW preview for %s: %s", photo_path, exc)
        return PhotoThumbnailResult(path=None, error=f"Failed to write preview: {exc}")


_PLACEHOLDER_CACHE: dict[bool, bytes] = {}


def build_photo_placeholder_bytes(raw: bool = False) -> bytes:
    """
    Return a visible placeholder image (PNG bytes).

    Renders a neutral gray tile with a label so the grid/viewer never shows a
    black screen with a tiny white pixel. Falls back to a 1x1 PNG only if
    Pillow is unavailable.
    """
    if raw in _PLACEHOLDER_CACHE:
        return _PLACEHOLDER_CACHE[raw]

    if Image is not None:
        try:
            import io

            from PIL import ImageDraw  # local import to avoid hard dependency at module load

            size = 480
            image = Image.new("RGB", (size, size), (38, 41, 48))
            draw = ImageDraw.Draw(image)
            # Simple framed icon look
            draw.rectangle((40, 40, size - 40, size - 40), outline=(90, 96, 108), width=3)
            label = "RAW" if raw else "No preview"
            # Centered-ish text (default font; positioning approximate)
            try:
                bbox = draw.textbbox((0, 0), label)
                tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            except Exception:  # noqa: BLE001
                tw, th = (len(label) * 6, 11)
            draw.text(((size - tw) / 2, (size - th) / 2), label, fill=(170, 176, 188))
            output = io.BytesIO()
            image.save(output, format="PNG", optimize=True)
            data = output.getvalue()
            _PLACEHOLDER_CACHE[raw] = data
            return data
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed to render placeholder image: %s", exc)

    # Fallback: 1x1 transparent PNG
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\x0cIDAT\x08\xd7c``\x00\x00\x00\x04\x00\x01"
        b"\x0d\n\x2d\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def _build_media_identity(path: Path, stat_size: int, stat_mtime: float, captured_at: datetime | None) -> str:
    timestamp = f"{captured_at.isoformat()}" if captured_at else "unknown"
    return f"{path.as_posix()}::{stat_size}::{stat_mtime:.6f}::{timestamp}"


def upsert_photo_record(
    db: Session,
    existing: Photo | None,
    file_path: Path,
    root: Path,
    *,
    media_source_id: int | None,
    stat_size: int,
    stat_mtime: float,
    stat_birthtime: float | None,
    metadata: PhotoMetadata,
    display_path: str,
    thumbnail_path: str | None,
    thumbnail_status: str,
    thumbnail_error: str | None,
    scan_status: str,
    scan_error: str | None,
) -> tuple[bool, bool, Photo]:
    relative_path = file_path.relative_to(root).as_posix()
    now = datetime.now(timezone.utc)
    media_identity = _build_media_identity(file_path, stat_size, stat_mtime, metadata.captured_at)
    file_created_at = _stat_to_datetime(stat_birthtime)
    file_modified_at = _stat_to_datetime(stat_mtime)

    if existing is None:
        photo = Photo(
            media_source_id=media_source_id,
            relative_path=relative_path,
            internal_path=str(file_path),
            display_path=display_path,
            filename=file_path.name,
            extension=file_path.suffix.lower(),
            file_size=stat_size,
            file_created_at=file_created_at,
            file_modified_at=file_modified_at,
            captured_at=metadata.captured_at,
            date_source=metadata.date_source,
            width=metadata.width,
            height=metadata.height,
            orientation=metadata.orientation,
            camera_make=metadata.camera_make,
            camera_model=metadata.camera_model,
            lens_model=metadata.lens_model,
            iso=metadata.iso,
            exposure_time=metadata.exposure_time,
            aperture=metadata.aperture,
            focal_length=metadata.focal_length,
            thumbnail_path=thumbnail_path,
            preview_path=None,
            preview_status="pending",
            preview_error=None,
            prepare_status="pending",
            prepare_error=None,
            prepared_at=None,
            media_identity=media_identity,
            scan_status=scan_status,
            thumbnail_status=thumbnail_status,
            thumbnail_error=thumbnail_error,
            scan_error=scan_error,
            raw_format=metadata.raw_format,
            created_at=now,
            updated_at=now,
        )
        db.add(photo)
        db.flush()
        return True, False, photo

    existing.media_source_id = media_source_id
    existing.relative_path = relative_path
    existing.internal_path = str(file_path)
    existing.display_path = display_path
    existing.filename = file_path.name
    existing.extension = file_path.suffix.lower()
    existing.file_size = stat_size
    existing.file_created_at = file_created_at
    existing.file_modified_at = file_modified_at
    existing.captured_at = metadata.captured_at
    existing.date_source = metadata.date_source
    existing.width = metadata.width
    existing.height = metadata.height
    existing.orientation = metadata.orientation
    existing.camera_make = metadata.camera_make
    existing.camera_model = metadata.camera_model
    existing.lens_model = metadata.lens_model
    existing.iso = metadata.iso
    existing.exposure_time = metadata.exposure_time
    existing.aperture = metadata.aperture
    existing.focal_length = metadata.focal_length
    existing.thumbnail_path = thumbnail_path
    existing.preview_path = None
    existing.preview_status = "pending"
    existing.preview_error = None
    existing.prepare_status = "pending"
    existing.prepare_error = None
    existing.prepared_at = None
    existing.media_identity = media_identity
    existing.scan_status = scan_status
    existing.thumbnail_status = thumbnail_status
    existing.thumbnail_error = thumbnail_error
    existing.scan_error = scan_error
    existing.raw_format = metadata.raw_format
    existing.updated_at = now
    return False, True, existing


def resolve_photo_original_path(photo: Photo, fallback_root: Path | None = None) -> Path:
    absolute_path = (photo.internal_path or "").strip()
    if absolute_path:
        return Path(absolute_path).expanduser().resolve(strict=False)
    if fallback_root is not None:
        return (fallback_root / photo.relative_path).expanduser().resolve(strict=False)
    raise ValueError("Photo record does not contain an original file path")


def normalize_folder_path(folder_path: str | None) -> str:
    return (folder_path or "").replace("\\", "/").strip("/")


def photo_folder_path_for(file_path: Path, root: Path) -> str:
    parent_relative = file_path.parent.relative_to(root)
    folder = parent_relative.as_posix()
    return "" if folder == "." else folder

