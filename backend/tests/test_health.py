from pathlib import Path

from tests.conftest import make_client


def test_health_endpoint(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
