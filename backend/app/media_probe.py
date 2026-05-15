import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ProbeResult:
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    video_codec: str | None = None
    audio_codec: str | None = None


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
        return ProbeResult()

    streams = payload.get("streams", [])
    format_info = payload.get("format", {})

    video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), {})

    duration: float | None = None
    raw_duration = format_info.get("duration")
    if raw_duration is not None:
        try:
            duration = float(raw_duration)
        except (TypeError, ValueError):
            duration = None

    return ProbeResult(
        duration=duration,
        width=video_stream.get("width"),
        height=video_stream.get("height"),
        video_codec=video_stream.get("codec_name"),
        audio_codec=audio_stream.get("codec_name"),
    )

