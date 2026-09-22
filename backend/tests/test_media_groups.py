from datetime import datetime, timezone
from pathlib import Path

from tests.conftest import make_client, setup_test_db


def _dt(year: int, month: int, day: int = 15) -> datetime:
    return datetime(year, month, day, 12, 0, 0, tzinfo=timezone.utc)


def _mk_video(tmp_path: Path, *, title: str, when: datetime, size: int = 100, duration: float = 60.0, folder: str = ""):
    from app.models import Video

    return Video(
        title=title,
        filename=f"{title}.mp4",
        relative_path=f"{title}.mp4",
        absolute_path=str(tmp_path / "videos" / f"{title}.mp4"),
        extension=".mp4",
        size=size,
        modified_ts=when.timestamp(),
        duration=duration,
        folder_path=folder,
        media_status="detected_video",
        probe_status="success",
        compatibility_status="direct_play",
        compatibility_reason="ok",
        indexed_at=when,
    )


def _mk_photo(tmp_path: Path, *, name: str, when: datetime, size: int = 200, source_id=None):
    from app.models import Photo

    return Photo(
        media_source_id=source_id,
        relative_path=f"{name}.jpg",
        internal_path=str(tmp_path / "videos" / f"{name}.jpg"),
        display_path=f"/volume1/{name}.jpg",
        filename=f"{name}.jpg",
        extension=".jpg",
        file_size=size,
        captured_at=when,
        date_source="file_modified",
        raw_format=False,
        scan_status="indexed",
        thumbnail_status="pending",
    )


def _seed(tmp_path: Path):
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        db.add_all([
            _mk_video(tmp_path, title="v2026a", when=_dt(2026, 7)),
            _mk_video(tmp_path, title="v2026b", when=_dt(2026, 6)),
            _mk_video(tmp_path, title="v2025a", when=_dt(2025, 3)),
            _mk_photo(tmp_path, name="p2026", when=_dt(2026, 7)),
            _mk_photo(tmp_path, name="p2024", when=_dt(2024, 12)),
        ])
        db.commit()
    finally:
        db.close()


def test_date_group_summary_returns_years_only(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    client = make_client(tmp_path)
    _seed(tmp_path)

    resp = client.get("/api/media/groups?type=all&group_by=date&order=desc")
    assert resp.status_code == 200
    groups = resp.json()
    assert [g["group_type"] for g in groups] == ["year", "year", "year"]
    assert [g["label"] for g in groups] == ["2026", "2025", "2024"]
    counts = {g["label"]: g["count"] for g in groups}
    assert counts == {"2026": 3, "2025": 1, "2024": 1}


def test_year_children_returns_months_only(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    client = make_client(tmp_path)
    _seed(tmp_path)

    resp = client.get("/api/media/groups?type=all&group_by=date&order=desc&year=2026")
    assert resp.status_code == 200
    groups = resp.json()
    assert [g["group_type"] for g in groups] == ["month", "month"]
    assert [g["label"] for g in groups] == ["July 2026", "June 2026"]
    assert [g["count"] for g in groups] == [2, 1]


def test_month_items_endpoint_paginates(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    client = make_client(tmp_path)
    _seed(tmp_path)

    resp = client.get(
        "/api/media/group-items?type=all&group_by=date&year=2026&month=7&sort=date&order=desc&offset=0&limit=1"
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["total"] == 2
    assert payload["offset"] == 0
    assert payload["limit"] == 1
    assert payload["has_more"] is True
    assert len(payload["items"]) == 1

    resp2 = client.get(
        "/api/media/group-items?type=all&group_by=date&year=2026&month=7&sort=date&order=desc&offset=1&limit=1"
    )
    payload2 = resp2.json()
    assert payload2["has_more"] is False
    assert len(payload2["items"]) == 1


def test_counts_respect_type_video(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    client = make_client(tmp_path)
    _seed(tmp_path)

    groups = client.get("/api/media/groups?type=video&group_by=date").json()
    counts = {g["label"]: g["count"] for g in groups}
    assert counts == {"2026": 2, "2025": 1}


def test_counts_respect_type_photo(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    client = make_client(tmp_path)
    _seed(tmp_path)

    groups = client.get("/api/media/groups?type=photo&group_by=date").json()
    counts = {g["label"]: g["count"] for g in groups}
    assert counts == {"2026": 1, "2024": 1}


def test_counts_respect_type_all(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    client = make_client(tmp_path)
    _seed(tmp_path)

    groups = client.get("/api/media/groups?type=all&group_by=date").json()
    assert sum(g["count"] for g in groups) == 5


def test_counts_respect_search_filter(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    client = make_client(tmp_path)
    _seed(tmp_path)

    groups = client.get("/api/media/groups?type=all&group_by=date&search=v2026a").json()
    counts = {g["label"]: g["count"] for g in groups}
    assert counts == {"2026": 1}


def test_counts_respect_tag_filter(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    client = make_client(tmp_path)

    from app.database import SessionLocal
    from app.models import Tag, VideoTag

    _seed(tmp_path)
    db = SessionLocal()
    try:
        from app.models import Video

        tag = Tag(name="Croatia", normalized_name="croatia", path="Croatia", depth=0, color=None)
        db.add(tag)
        db.flush()
        v = db.query(Video).filter(Video.title == "v2026a").first()
        db.add(VideoTag(video_id=v.id, tag_id=tag.id))
        db.commit()
        tag_id = tag.id
    finally:
        db.close()

    groups = client.get(f"/api/media/groups?type=all&group_by=date&tag_ids={tag_id}").json()
    counts = {g["label"]: g["count"] for g in groups}
    assert counts == {"2026": 1}


def test_date_order_asc_desc_affects_order(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    client = make_client(tmp_path)
    _seed(tmp_path)

    asc = client.get("/api/media/groups?type=all&group_by=date&order=asc").json()
    desc = client.get("/api/media/groups?type=all&group_by=date&order=desc").json()
    assert [g["label"] for g in asc] == ["2024", "2025", "2026"]
    assert [g["label"] for g in desc] == ["2026", "2025", "2024"]

    months_asc = client.get("/api/media/groups?type=all&group_by=date&order=asc&year=2026").json()
    assert [g["label"] for g in months_asc] == ["June 2026", "July 2026"]


def test_pagination_has_more(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    client = make_client(tmp_path)
    _seed(tmp_path)

    resp = client.get("/api/media/group-items?type=all&group_by=date&year=2026&limit=2&offset=0").json()
    assert resp["total"] == 3
    assert resp["has_more"] is True
    assert len(resp["items"]) == 2

    resp2 = client.get("/api/media/group-items?type=all&group_by=date&year=2026&limit=2&offset=2").json()
    assert resp2["has_more"] is False
    assert len(resp2["items"]) == 1


def test_playlist_scoped_groups_only_playlist_items(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    client = make_client(tmp_path)
    _seed(tmp_path)

    from app.database import SessionLocal
    from app.models import Playlist, PlaylistItem, Video

    db = SessionLocal()
    try:
        pl = Playlist(name="pl")
        db.add(pl)
        db.flush()
        v = db.query(Video).filter(Video.title == "v2025a").first()
        db.add(PlaylistItem(playlist_id=pl.id, video_id=v.id, position=0))
        db.commit()
        pl_id = pl.id
    finally:
        db.close()

    groups = client.get(f"/api/media/groups?type=all&group_by=date&playlist_id={pl_id}").json()
    counts = {g["label"]: g["count"] for g in groups}
    assert counts == {"2025": 1}


def test_folder_scoped_groups_only_folder_items(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    client = make_client(tmp_path)

    from app.database import SessionLocal

    db = SessionLocal()
    try:
        db.add_all([
            _mk_video(tmp_path, title="root", when=_dt(2026, 1), folder=""),
            _mk_video(tmp_path, title="inA", when=_dt(2026, 2), folder="A"),
            _mk_video(tmp_path, title="inA2", when=_dt(2025, 2), folder="A"),
        ])
        db.commit()
    finally:
        db.close()

    groups = client.get("/api/media/groups?type=video&group_by=date&folder=A").json()
    counts = {g["label"]: g["count"] for g in groups}
    assert counts == {"2026": 1, "2025": 1}


def test_file_size_buckets(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    client = make_client(tmp_path)

    from app.database import SessionLocal

    GIB = 1024 * 1024 * 1024
    db = SessionLocal()
    try:
        db.add_all([
            _mk_video(tmp_path, title="small", when=_dt(2026, 1), size=500),
            _mk_video(tmp_path, title="big", when=_dt(2026, 1), size=5 * GIB),
        ])
        db.commit()
    finally:
        db.close()

    groups = client.get("/api/media/groups?type=video&group_by=file_size&order=desc").json()
    labels = [g["label"] for g in groups]
    assert "1-20 GB" in labels
    assert "Under 1 GB" in labels
    # desc → largest bucket first
    assert labels.index("1-20 GB") < labels.index("Under 1 GB")

    items = client.get("/api/media/group-items?type=video&group_by=file_size&bucket=under1gib&sort=file_size").json()
    assert items["total"] == 1
    assert items["items"][0]["display_title"] == "small"


def test_existing_media_endpoint_still_works(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    client = make_client(tmp_path)
    _seed(tmp_path)

    resp = client.get("/api/media?type=all")
    assert resp.status_code == 200
    assert resp.json()["total"] == 5
