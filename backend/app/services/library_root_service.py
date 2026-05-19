from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import Settings
from app.models import LibraryRoot, Video
from app.schemas import PathValidationResult
from app.utils.files import safe_resolve_under_root

logger = logging.getLogger(__name__)

DEFAULT_LIBRARY_ROOT_NAME = "Default"

# Synology host mount root – displayed to the user as the "host" prefix.
# /volume1 is mounted as /media in the container.
_HOST_DISPLAY_ROOT = "/volume1"

# Directory names inside the media root that are always hidden from browse + blocked as sources.
_BROWSE_HIDDEN_NAMES: frozenset[str] = frozenset(
    n.lower() for n in {"@eaDir", "@tmp", "#recycle", "$RECYCLE.BIN", "System Volume Information"}
)


# ── Path helpers ───────────────────────────────────────────────────────────


def _resolve_media_base(settings: Settings) -> Path:
    return Path(settings.video_library_path).expanduser().resolve(strict=False)


def normalize_media_source_path(path_str: str) -> str:
    return str(Path(path_str).expanduser().resolve(strict=False))


def _is_media_base_path(path: Path, settings: Settings) -> bool:
    """Return True if *path* is exactly the mounted media root (e.g. /media)."""
    return path.resolve(strict=False) == _resolve_media_base(settings)


def _is_blocked_runtime_path(path: Path, settings: Settings) -> bool:
    """Return True if *path* overlaps with app infrastructure visible under the media mount.

    Host path /volume1/docker/ maps to /media/docker/ inside the container.
    We block all of /media/docker/** as those contain project and runtime files.
    """
    try:
        media_base = _resolve_media_base(settings)
        resolved = path.resolve(strict=False)
        rel = resolved.relative_to(media_base)
        parts = rel.parts
        if parts and parts[0] == "docker":
            return True
    except (ValueError, OSError):
        pass
    return False


def path_to_relative(path: Path, settings: Settings) -> str:
    """Return *path* as a string relative to the media root.  Empty string if not under root."""
    try:
        media_base = _resolve_media_base(settings)
        return path.resolve(strict=False).relative_to(media_base).as_posix()
    except (ValueError, OSError):
        return ""


def path_to_display(path: Path, settings: Settings) -> str:
    """Return a human-readable host-side path (e.g. /volume1/sclad/Movies)."""
    rel = path_to_relative(path, settings)
    if rel:
        return f"{_HOST_DISPLAY_ROOT}/{rel}"
    return str(path)


# ── Validation ─────────────────────────────────────────────────────────────


def validate_media_source_path(path_str: str, settings: Settings) -> PathValidationResult:
    normalized = path_str.strip()
    if not normalized:
        return PathValidationResult(valid=False, code="empty_path", message="Path cannot be empty.")

    try:
        path = Path(normalized).expanduser().resolve(strict=False)
    except Exception as exc:  # noqa: BLE001
        return PathValidationResult(valid=False, code="invalid_path", message=f"Invalid path: {exc}")

    # Reject the mounted base root itself
    if _is_media_base_path(path, settings):
        return PathValidationResult(
            valid=False,
            path=str(path),
            code="root_source_not_allowed",
            message=(
                "Please select a subfolder. "
                "The mounted root itself (/volume1) is not scanned directly."
            ),
        )

    # Reject blocked runtime paths (docker infrastructure visible under /media)
    if _is_blocked_runtime_path(path, settings):
        return PathValidationResult(
            valid=False,
            path=str(path),
            code="runtime_path_blocked",
            message=(
                "This folder contains application infrastructure and cannot be used as a media source."
            ),
        )

    allowed_bases_raw = settings.allowed_media_root_bases.strip()
    if allowed_bases_raw:
        allowed_bases = [
            Path(item.strip()).expanduser().resolve(strict=False)
            for item in allowed_bases_raw.split(",")
            if item.strip()
        ]
        if allowed_bases:
            in_allowed = any(path == base or base in path.parents for base in allowed_bases)
            if not in_allowed:
                return PathValidationResult(
                    valid=False,
                    code="outside_allowed_bases",
                    message=f"Path must be inside one of: {', '.join(str(b) for b in allowed_bases)}",
                )

    if not path.exists():
        return PathValidationResult(
            valid=False,
            path=str(path),
            code="path_not_found",
            message=f"Path does not exist: {path}",
        )

    if not path.is_dir():
        return PathValidationResult(
            valid=False,
            path=str(path),
            code="not_directory",
            message=f"Path is not a directory: {path}",
        )

    if not os.access(path, os.R_OK):
        return PathValidationResult(
            valid=False,
            path=str(path),
            code="not_readable",
            message=f"Path is not readable by the container user: {path}",
        )

    return PathValidationResult(valid=True, path=str(path), message="Path is valid and readable.")


# ── Browse ─────────────────────────────────────────────────────────────────


@dataclass
class MediaSourceBrowseEntry:
    name: str
    relative_path: str   # relative to media base, e.g. "sclad/Movies"
    internal_path: str   # absolute container path, e.g. "/media/sclad/Movies"
    display_path: str    # host-side display path, e.g. "/volume1/sclad/Movies"
    is_directory: bool
    already_added: bool
    blocked: bool


def browse_media_sources(
    relative_path: str,
    settings: Settings,
    db: Session,
) -> list[MediaSourceBrowseEntry]:
    """List direct child directories under the media root (or a sub-path).

    Never escapes the media root.  Filters out hidden/system directories.
    Marks blocked paths (the root itself, docker/**) and already-added paths.
    """
    media_base = _resolve_media_base(settings)

    # Resolve browse target safely – strip traversal components
    stripped = relative_path.strip().lstrip("/")
    if not stripped or stripped == ".":
        browse_target = media_base
    else:
        safe_parts = [p for p in Path(stripped).parts if p not in ("..", ".")]
        browse_target = media_base.joinpath(*safe_parts) if safe_parts else media_base

    # Ensure we haven't escaped the media root
    try:
        browse_target.resolve(strict=False).relative_to(media_base)
    except ValueError:
        return []

    if not browse_target.exists() or not browse_target.is_dir():
        return []

    # Collect already-configured paths for quick lookup
    existing_paths: set[str] = {
        Path(r.path).resolve(strict=False).as_posix()
        for (r,) in db.query(LibraryRoot).with_entities(LibraryRoot.path).all()
    }

    entries: list[MediaSourceBrowseEntry] = []
    try:
        for child in sorted(browse_target.iterdir()):
            if not child.is_dir():
                continue
            if child.name.startswith(".") or child.name.lower() in _BROWSE_HIDDEN_NAMES:
                continue

            rel_str = path_to_relative(child, settings)
            display = path_to_display(child, settings)
            blocked = _is_blocked_runtime_path(child, settings)
            already = child.resolve(strict=False).as_posix() in existing_paths

            entries.append(
                MediaSourceBrowseEntry(
                    name=child.name,
                    relative_path=rel_str,
                    internal_path=str(child),
                    display_path=display,
                    is_directory=True,
                    already_added=already,
                    blocked=blocked,
                )
            )
    except PermissionError:
        pass

    return entries


# ── Bootstrap from environment variables ──────────────────────────────────


def _dedupe_root_configs(configs: list[dict[str, object]]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    seen_paths: set[str] = set()
    for config in configs:
        raw_path = str(config.get("path") or "").strip()
        if not raw_path:
            continue
        normalized_path = normalize_media_source_path(raw_path)
        if normalized_path in seen_paths:
            continue
        seen_paths.add(normalized_path)
        result.append(
            {
                "name": str(config.get("name") or DEFAULT_LIBRARY_ROOT_NAME).strip() or DEFAULT_LIBRARY_ROOT_NAME,
                "path": normalized_path,
                "media_type": str(config.get("media_type") or "video").strip() or "video",
                "enabled": bool(config.get("enabled", True)),
                "recursive": bool(config.get("recursive", True)),
                "scan_priority": int(config.get("scan_priority", 100)),
            }
        )
    return result


def _root_configs_from_env(settings: Settings) -> list[dict[str, object]]:
    """Return root configs from MEDIA_LIBRARY_ROOTS or MEDIA_LIBRARY_ROOTS_JSON env vars.

    Returns an empty list if neither is set.  Does NOT fall back to VIDEO_LIBRARY_PATH.
    """
    if settings.media_library_roots_json.strip():
        try:
            payload = json.loads(settings.media_library_roots_json)
            if isinstance(payload, list):
                configs = _dedupe_root_configs([item for item in payload if isinstance(item, dict)])
                if configs:
                    return configs
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to parse MEDIA_LIBRARY_ROOTS_JSON: %s", exc)

    if settings.media_library_roots.strip():
        paths = [item.strip() for item in settings.media_library_roots.split(",") if item.strip()]
        configs = _dedupe_root_configs(
            [
                {
                    "name": f"Library {index + 1}" if len(paths) > 1 else DEFAULT_LIBRARY_ROOT_NAME,
                    "path": path,
                    "media_type": "video",
                    "enabled": True,
                    "recursive": True,
                    "scan_priority": 100 + index * 10,
                }
                for index, path in enumerate(paths)
            ]
        )
        if configs:
            return configs

    # No explicit configuration – return empty (do NOT auto-create from VIDEO_LIBRARY_PATH)
    return []


def bootstrap_library_roots(db: Session, settings: Settings) -> list[LibraryRoot]:
    """Create library roots from MEDIA_LIBRARY_ROOTS/JSON env vars if not yet done.

    If neither env var is set, this is a no-op and an empty list is returned.
    The old behaviour of auto-creating a 'Default' source from VIDEO_LIBRARY_PATH
    has been removed to prevent /media (the mounted root) being scanned automatically.
    """
    if db.query(LibraryRoot).count() > 0:
        return db.query(LibraryRoot).order_by(LibraryRoot.scan_priority.asc(), LibraryRoot.name.asc()).all()

    configs = _root_configs_from_env(settings)
    if not configs:
        return []

    roots: list[LibraryRoot] = []
    for config in configs:
        root = LibraryRoot(
            name=str(config["name"]),
            path=str(config["path"]),
            media_type=str(config["media_type"]),
            enabled=bool(config["enabled"]),
            recursive=bool(config["recursive"]),
            scan_priority=int(config["scan_priority"]),
        )
        db.add(root)
        roots.append(root)

    db.commit()
    for root in roots:
        db.refresh(root)

    logger.info("Initialized %d library root(s) from environment variables", len(roots))
    return roots


# ── Startup cleanup for legacy invalid default source ────────────────────


def clean_up_invalid_default_source(db: Session, settings: Settings) -> int:
    """Remove auto-created 'Default' library roots that point to the media mount base.

    Older versions of the app automatically created a 'Default' source from
    VIDEO_LIBRARY_PATH (e.g. /media) when no sources were configured.  This
    caused the entire /volume1 to be scanned and appeared as 'Default /media'
    in the UI.  This function silently removes such entries on startup.

    Returns the number of sources removed.
    """
    media_base_str = str(_resolve_media_base(settings))
    stale = (
        db.query(LibraryRoot)
        .filter(
            LibraryRoot.name == DEFAULT_LIBRARY_ROOT_NAME,
            LibraryRoot.path == media_base_str,
        )
        .all()
    )
    if not stale:
        return 0
    for root in stale:
        logger.info(
            "Removing legacy invalid default media root (id=%s path=%s). "
            "Configure media sources via Settings → Media Sources.",
            root.id,
            root.path,
        )
        db.delete(root)
    db.commit()
    return len(stale)


# ── Query helpers ──────────────────────────────────────────────────────────


def get_enabled_library_roots(db: Session, settings: Settings) -> list[LibraryRoot]:
    """Return all enabled library roots.  Never auto-creates a default source."""
    return (
        db.query(LibraryRoot)
        .filter(LibraryRoot.enabled.is_(True))
        .order_by(LibraryRoot.scan_priority.asc(), LibraryRoot.name.asc(), LibraryRoot.id.asc())
        .all()
    )


def resolve_video_source_path(video: Video, settings: Settings) -> Path:
    absolute_path = (video.absolute_path or "").strip()
    if absolute_path:
        return Path(absolute_path).expanduser().resolve(strict=False)
    return safe_resolve_under_root(settings.video_library_path, video.relative_path)

