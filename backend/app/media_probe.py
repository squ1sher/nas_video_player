import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ProbeResult:
    success: bool = False
    has_video_stream: bool = False
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    video_codec: str | None = None
    video_profile: str | None = None
    video_level: str | None = None
    pixel_format: str | None = None
    audio_codec: str | None = None
    audio_channels: int | None = None
    audio_sample_rate: int | None = None
    container_format: str | None = None
    error: str | None = None


def probe_video(path: Path) -> ProbeResult:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]

    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, check=True)
        payload = json.loads(completed.stdout or "{}")
    except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        logger.error("ffprobe failed for %s: %s", path, exc)
        return ProbeResult(success=False, error=str(exc))

    streams = payload.get("streams", [])
    format_info = payload.get("format", {})

    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), {})

    duration: float | None = None
    raw_duration = format_info.get("duration")
    if raw_duration is not None:
        try:
            duration = float(raw_duration)
        except (TypeError, ValueError):
            duration = None

    format_name = format_info.get("format_name")
    has_video_stream = video_stream is not None

    return ProbeResult(
        success=True,
        has_video_stream=has_video_stream,
        duration=duration,
        width=video_stream.get("width") if video_stream else None,
        height=video_stream.get("height") if video_stream else None,
        video_codec=video_stream.get("codec_name") if video_stream else None,
        video_profile=video_stream.get("profile") if video_stream else None,
        video_level=str(video_stream.get("level")) if video_stream and video_stream.get("level") is not None else None,
        pixel_format=video_stream.get("pix_fmt") if video_stream else None,
        audio_codec=audio_stream.get("codec_name"),
        audio_channels=audio_stream.get("channels"),
        audio_sample_rate=int(audio_stream.get("sample_rate")) if audio_stream.get("sample_rate") else None,
        container_format=format_name,
        error=None,
    )

