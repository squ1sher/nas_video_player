import subprocess
from pathlib import Path

from app.media_probe import probe_video
from app.scanner import iter_video_files


def test_scanner_filters_extensions(tmp_path: Path) -> None:
    (tmp_path / "a.mp4").write_bytes(b"a")
    (tmp_path / "b.mkv").write_bytes(b"b")
    (tmp_path / "c.txt").write_bytes(b"c")

    results = iter_video_files(tmp_path)
    names = sorted(path.name for path in results)
    assert names == ["a.mp4", "b.mkv"]


def test_probe_video_fallback_on_error(monkeypatch) -> None:
    def _raise(*args, **kwargs):
        raise subprocess.CalledProcessError(returncode=1, cmd="ffprobe")

    monkeypatch.setattr("subprocess.run", _raise)
    result = probe_video(Path("/tmp/missing.mp4"))

    assert result.duration is None
    assert result.width is None
    assert result.height is None
    assert result.video_codec is None
    assert result.audio_codec is None

