"""Tests for browser compatibility detection."""
import pytest

from app.compatibility import get_compatibility


class TestDirectPlay:
    def test_mp4_h264_aac(self) -> None:
        result = get_compatibility(".mp4", "h264", "aac")
        assert result["status"] == "direct_play"

    def test_m4v_h264_aac(self) -> None:
        result = get_compatibility(".m4v", "h264", "aac")
        assert result["status"] == "direct_play"

    def test_webm_vp9_opus(self) -> None:
        result = get_compatibility(".webm", "vp9", "opus")
        assert result["status"] == "direct_play"

    def test_webm_vp8_vorbis(self) -> None:
        result = get_compatibility(".webm", "vp8", "vorbis")
        assert result["status"] == "direct_play"

    def test_webm_av1_opus(self) -> None:
        result = get_compatibility(".webm", "av1", "opus")
        assert result["status"] == "direct_play"


class TestMayNotPlay:
    def test_mkv(self) -> None:
        result = get_compatibility(".mkv", "h264", "aac")
        assert result["status"] == "may_not_play"

    def test_mov(self) -> None:
        result = get_compatibility(".mov", "h264", "aac")
        assert result["status"] == "may_not_play"

    def test_mp4_unknown_codec(self) -> None:
        result = get_compatibility(".mp4", "mpeg4", "mp3")
        assert result["status"] == "may_not_play"

    def test_unknown_extension(self) -> None:
        result = get_compatibility(".flv", "h264", "aac")
        assert result["status"] == "may_not_play"


class TestNeedsConversion:
    def test_avi(self) -> None:
        result = get_compatibility(".avi", "mpeg4", "mp3")
        assert result["status"] == "needs_conversion"

    def test_dts_audio(self) -> None:
        result = get_compatibility(".mkv", "h264", "dts")
        assert result["status"] == "needs_conversion"

    def test_hevc(self) -> None:
        result = get_compatibility(".mp4", "hevc", "aac")
        assert result["status"] == "needs_conversion"

    def test_h265(self) -> None:
        result = get_compatibility(".mkv", "h265", "ac3")
        assert result["status"] == "needs_conversion"

    def test_dts_hd(self) -> None:
        result = get_compatibility(".mkv", "h264", "dts_hd")
        assert result["status"] == "needs_conversion"


def test_reason_is_always_present() -> None:
    for ext, vc, ac in [
        (".mp4", "h264", "aac"),
        (".avi", None, None),
        (".mkv", "h264", "dts"),
        (".xyz", None, None),
    ]:
        result = get_compatibility(ext, vc, ac)
        assert "reason" in result
        assert result["reason"]
