from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import Settings
from app.models import LibraryRoot, Video
from app.schemas import PathValidationResult
from app.utils.files import safe_resolve_under_root

logger = logging.getLogger(__name__)


DEFAULT_LIBRARY_ROOT_NAME = "Default"


def normalize_media_source_path(path_str: str) -> str:
    return str(Path(path_str).expanduser().resolve(strict=False))


def validate_media_source_path(path_str: str, settings: Settings) -> PathValidationResult:
    normalized = path_str.strip()
    if not normalized:
        return PathValidationResult(valid=False, code="empty_path", message="Path cannot be empty.")

    try:
        path = Path(normalized).expanduser().resolve(strict=False)
    except Exception as exc:  # noqa: BLE001
        return PathValidationResult(valid=False, code="invalid_path", message=f"Invalid path: {exc}")

    allowed_bases_raw = settings.allowed_media_root_bases.strip()
    if allowed_bases_raw:
        allowed_bases = [Path(item.strip()).expanduser().resolve(strict=False) for item in allowed_bases_raw.split(",") if item.strip()]
        if allowed_bases:
            in_allowed = any(path == base or base in path.parents for base in allowed_bases)
            if not in_allowed:
                return PathValidationResult(
                    valid=False,
                    code="outside_allowed_bases",
                    message=f"Path must be inside one of: {', '.join(str(base) for base in allowed_bases)}",
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


def _root_configs_from_settings(settings: Settings) -> list[dict[str, object]]:
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

    return [
        {
            "name": DEFAULT_LIBRARY_ROOT_NAME,
            "path": normalize_media_source_path(str(settings.video_library_path)),
            "media_type": "video",
            "enabled": True,
            "recursive": True,
            "scan_priority": 100,
        }
    ]


def bootstrap_library_roots(db: Session, settings: Settings) -> list[LibraryRoot]:
    if db.query(LibraryRoot).count() > 0:
        return db.query(LibraryRoot).order_by(LibraryRoot.scan_priority.asc(), LibraryRoot.name.asc()).all()

    roots: list[LibraryRoot] = []
    for config in _root_configs_from_settings(settings):
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

    logger.info("Initialized %d library root(s)", len(roots))
    return roots


def get_enabled_library_roots(db: Session, settings: Settings) -> list[LibraryRoot]:
    if db.query(LibraryRoot).count() == 0:
        bootstrap_library_roots(db, settings)
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


