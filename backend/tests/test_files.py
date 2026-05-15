from pathlib import Path

import pytest

from app.utils.files import safe_resolve_under_root


def test_safe_resolve_within_root(tmp_path: Path) -> None:
    root = tmp_path / "videos"
    file_path = root / "movie.mp4"
    file_path.parent.mkdir(parents=True)
    file_path.write_bytes(b"demo")

    resolved = safe_resolve_under_root(root, "movie.mp4")
    assert resolved == file_path.resolve()


def test_safe_resolve_rejects_traversal(tmp_path: Path) -> None:
    root = tmp_path / "videos"
    outside = tmp_path / "secret.mp4"
    root.mkdir(parents=True)
    outside.write_bytes(b"secret")

    with pytest.raises(ValueError):
        safe_resolve_under_root(root, "../secret.mp4")

