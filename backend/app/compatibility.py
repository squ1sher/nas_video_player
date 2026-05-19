"""Browser compatibility detection for video files.

Determines whether a video file can be played directly in a browser
based on container format, video codec, and audio codec.
"""


def get_compatibility(extension: str, video_codec: str | None, audio_codec: str | None) -> dict[str, str]:
    """Return a dict with 'status' and 'reason' for the given video specs.

    Possible statuses:
      - direct_play   : browser can play without transcoding
      - may_play      : likely to play in some browsers
      - may_not_play  : likely not to play in most browsers
      - needs_conversion : will not play in any modern browser without transcoding
      - unknown       : metadata missing, cannot estimate
    """
    ext = extension.lower().lstrip(".")
    vc = (video_codec or "").lower()
    ac = (audio_codec or "").lower()

    if not vc and not ac:
        return {
            "status": "unknown",
            "reason": "Not enough codec metadata to estimate browser playback support.",
        }

    # --- needs_conversion (hard blockers) ---
    if ext == "avi":
        return {
            "status": "needs_conversion",
            "reason": "AVI container is not supported by modern browsers.",
        }
    if "dts" in ac:
        return {
            "status": "needs_conversion",
            "reason": "DTS audio is not supported by browsers. Transcoding required.",
        }
    if "hevc" in vc or "h265" in vc or "h.265" in vc:
        return {
            "status": "needs_conversion",
            "reason": "HEVC/H.265 video is not widely supported. Transcoding required.",
        }

    # --- direct_play ---
    if ext in ("mp4", "m4v") and "h264" in vc and ac in ("aac", "mp4a", "mp4a.40"):
        return {
            "status": "direct_play",
            "reason": "MP4 + H.264 + AAC is fully supported by all modern browsers.",
        }
    if ext == "webm" and vc in ("vp8", "vp9", "av1") and ac in ("opus", "vorbis"):
        return {
            "status": "direct_play",
            "reason": "WebM + VP8/VP9/AV1 + Opus/Vorbis is fully supported by modern browsers.",
        }

    # --- may_not_play ---
    if ext == "mkv":
        return {
            "status": "may_not_play",
            "reason": "MKV container has limited browser support. Playback depends on codecs.",
        }
    if ext == "mov":
        return {
            "status": "may_not_play",
            "reason": "MOV container may not be supported in all browsers.",
        }
    if ext in ("mp4", "m4v"):
        # MP4 with non-ideal codec combination
        return {
            "status": "may_not_play",
            "reason": f"MP4 with {vc or 'unknown'} video / {ac or 'unknown'} audio may not play in all browsers.",
        }
    if ext == "webm":
        return {
            "status": "may_not_play",
            "reason": f"WebM with {vc or 'unknown'} video / {ac or 'unknown'} audio may not play in all browsers.",
        }
    if ext in ("mpg", "mpeg"):
        return {
            "status": "may_play",
            "reason": "MPEG container support varies by browser and codec.",
        }

    # --- unknown / catch-all ---
    return {
        "status": "may_not_play",
        "reason": f"Unknown format: {ext} container with {vc or 'unknown'} video / {ac or 'unknown'} audio.",
    }

