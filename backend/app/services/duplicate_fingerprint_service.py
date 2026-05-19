from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite

from app.models import Video

FINGERPRINT_VERSION = "v1"
DUPLICATE_MODES = {"strict"}


@dataclass(frozen=True)
class DuplicateFingerprint:
    mode: str
    version: str
    file_size: int
    duration_seconds: int | None
    width: int | None
    height: int | None
    video_codec: str | None
    audio_codec: str | None
    extension: str | None
    normalized_title: str | None

    def to_dict(self) -> dict[str, str | int | None]:
        return asdict(self)


def normalize_codec(codec: str | None) -> str | None:
    if not codec:
        return None
    return codec.strip().lower().replace(" ", "_")


def normalize_extension(extension: str | None) -> str | None:
    if not extension:
        return None
    ext = extension.strip().lower()
    return ext if ext.startswith(".") else f".{ext}"


def normalize_title(title: str | None) -> str | None:
    if not title:
        return None
    normalized = " ".join(title.lower().replace("_", " ").replace("-", " ").split())
    return normalized or None


def round_duration_seconds(duration: float | None) -> int | None:
    if duration is None or not isfinite(duration) or duration < 0:
        return None
    return int(round(duration))


def build_duplicate_fingerprint(video: Video, mode: str = "strict") -> DuplicateFingerprint:
    if mode not in DUPLICATE_MODES:
        raise ValueError(f"Unsupported duplicate mode: {mode}")

    return DuplicateFingerprint(
        mode=mode,
        version=FINGERPRINT_VERSION,
        file_size=int(video.size),
        duration_seconds=round_duration_seconds(video.duration),
        width=video.width,
        height=video.height,
        video_codec=normalize_codec(video.video_codec),
        audio_codec=normalize_codec(video.audio_codec),
        extension=normalize_extension(video.extension),
        normalized_title=normalize_title(video.title),
    )


def build_strict_group_key(video: Video) -> str | None:
    fingerprint = build_duplicate_fingerprint(video, mode="strict")
    required_values = [
        fingerprint.file_size,
        fingerprint.duration_seconds,
        fingerprint.width,
        fingerprint.height,
    ]
    if any(value is None for value in required_values):
        return None

    return "|".join(
        [
            FINGERPRINT_VERSION,
            str(fingerprint.file_size),
            str(fingerprint.duration_seconds),
            str(fingerprint.width),
            str(fingerprint.height),
        ]
    )




