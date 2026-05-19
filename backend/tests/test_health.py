from pathlib import Path

from tests.conftest import make_client


def test_health_endpoint(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["runtime_dirs"] == {
        "database": str(tmp_path / "data"),
        "thumbnails": str(tmp_path / "thumbnails"),
        "cache": str(tmp_path / "cache"),
        "hls": str(tmp_path / "cache" / "hls"),
        "logs": str(tmp_path / "logs"),
    }
