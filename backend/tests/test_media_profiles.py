from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from tests.conftest import make_client, setup_test_db


def _insert_video(tmp_path: Path, *, relative_path: str, extension: str, video_codec: str, pixel_format: str, audio_codec: str) -> int:
    from app.database import SessionLocal
    from app.models import Video

    db = SessionLocal()
    now = datetime.now(timezone.utc)
    video = Video(
        title=relative_path,
        filename=relative_path.split("/")[-1],
        relative_path=relative_path,
        absolute_path=str(tmp_path / "videos" / relative_path),
        extension=extension,
        size=123,
        modified_ts=now.timestamp(),
        duration=10.0,
        width=1920,
        height=1080,
        video_codec=video_codec,
        pixel_format=pixel_format,
        audio_codec=audio_codec,
        media_status="detected_video",
        probe_status="success",
        compatibility_status="unknown",
        compatibility_reason="test",
        indexed_at=now,
        created_at=now,
    )
    db.add(video)
    db.commit()
    db.refresh(video)
    video_id = video.id
    db.close()
    return video_id


def test_profile_key_is_deterministic_and_ignores_path(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    from app.services.media_profile_service import build_media_profile_fields

    first = build_media_profile_fields(
        extension=".MP4",
        container_format="mov,mp4,m4a,3gp,3g2,mj2",
        video_codec="H264",
        video_profile="High",
        video_level="42",
        pixel_format="YUV420P",
        audio_codec="AAC",
        audio_channels=2,
        audio_sample_rate=48000,
        width=3840,
        height=1920,
    )
    second = build_media_profile_fields(
        extension="mp4",
        container_format="mp4,mov,m4a,3gp,3g2,mj2",
        video_codec="h264",
        video_profile="high",
        video_level="42",
        pixel_format="yuv420p",
        audio_codec="aac",
        audio_channels=2,
        audio_sample_rate=48000,
        width=3840,
        height=1920,
    )

    assert first["profile_key"] == second["profile_key"]


def test_codec_aliases_are_normalized(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    from app.services.media_profile_service import build_media_profile_fields

    hevc_alias = build_media_profile_fields(
        extension=".mkv",
        container_format="matroska,webm",
        video_codec="x265",
        video_profile="main",
        video_level="120",
        pixel_format="yuv420p10le",
        audio_codec="ac-3",
        audio_channels=6,
        audio_sample_rate=48000,
        width=1920,
        height=1080,
    )

    assert hevc_alias["video_codec"] == "hevc"
    assert hevc_alias["audio_codec"] == "ac3"


def test_same_profile_maps_to_same_key_different_codec_maps_to_different_key(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    from app.services.media_profile_service import build_media_profile_fields

    a = build_media_profile_fields(
        extension=".360",
        container_format="mov,mp4,m4a,3gp,3g2,mj2",
        video_codec="h264",
        video_profile="high",
        video_level="42",
        pixel_format="yuv420p",
        audio_codec="aac",
        audio_channels=2,
        audio_sample_rate=48000,
        width=3840,
        height=1920,
    )
    b = build_media_profile_fields(
        extension=".360",
        container_format="mov,mp4,m4a,3gp,3g2,mj2",
        video_codec="h264",
        video_profile="high",
        video_level="42",
        pixel_format="yuv420p",
        audio_codec="aac",
        audio_channels=2,
        audio_sample_rate=48000,
        width=3840,
        height=1920,
    )
    c = build_media_profile_fields(
        extension=".360",
        container_format="mov,mp4,m4a,3gp,3g2,mj2",
        video_codec="hevc",
        video_profile="main",
        video_level="120",
        pixel_format="yuv420p10le",
        audio_codec="aac",
        audio_channels=2,
        audio_sample_rate=48000,
        width=3840,
        height=1920,
    )

    assert a["profile_key"] == b["profile_key"]
    assert a["profile_key"] != c["profile_key"]


def test_manual_profile_override_and_clear_updates_videos(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    video_id = _insert_video(
        tmp_path,
        relative_path="GoPro/GX010123.360",
        extension=".360",
        video_codec="h264",
        pixel_format="yuv420p",
        audio_codec="aac",
    )

    from app.database import SessionLocal
    from app.models import Video
    from app.services.media_profile_service import (
        assign_profile_to_video,
        build_media_profile_fields,
        compute_auto_compatibility,
        upsert_media_profile,
    )

    db = SessionLocal()
    video = db.query(Video).filter(Video.id == video_id).first()
    assert video is not None
    fields = build_media_profile_fields(
        extension=video.extension,
        container_format="mov,mp4,m4a,3gp,3g2,mj2",
        video_codec=video.video_codec,
        video_profile="high",
        video_level="42",
        pixel_format=video.pixel_format,
        audio_codec=video.audio_codec,
        audio_channels=2,
        audio_sample_rate=48000,
        width=video.width,
        height=video.height,
    )
    auto_status, auto_reason = compute_auto_compatibility(video.extension, video.video_codec, video.audio_codec)
    profile = upsert_media_profile(db, fields, auto_status=auto_status, auto_reason=auto_reason)
    assign_profile_to_video(video, profile)
    if profile.sample_video_id is None:
        profile.sample_video_id = video.id
    db.commit()
    profile_id = profile.id
    db.close()

    response = client.put(
        f"/api/media-profiles/{profile_id}/playback-status",
        json={"manual_playback_status": "playable", "manual_playback_note": "Plays in Chrome"},
    )
    assert response.status_code == 200
    updated_profile = response.json()
    assert updated_profile["manual_playback_status"] == "playable"
    assert updated_profile["effective_compatibility_status"] == "direct_play"
    assert updated_profile["compatibility_source"] == "manual_profile_override"

    video_data = client.get(f"/api/videos/{video_id}").json()
    assert video_data["effective_compatibility_status"] == "direct_play"
    assert video_data["compatibility_source"] == "manual_profile_override"

    clear = client.delete(f"/api/media-profiles/{profile_id}/playback-status")
    assert clear.status_code == 200
    cleared_profile = clear.json()
    assert cleared_profile["manual_playback_status"] is None
    assert cleared_profile["compatibility_source"] == "auto_heuristic"


def test_media_profiles_list_returns_files_count_and_sample_video(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    v1 = _insert_video(tmp_path, relative_path="A/a.360", extension=".360", video_codec="h264", pixel_format="yuv420p", audio_codec="aac")
    v2 = _insert_video(tmp_path, relative_path="A/b.360", extension=".360", video_codec="h264", pixel_format="yuv420p", audio_codec="aac")

    from app.database import SessionLocal
    from app.models import Video
    from app.services.media_profile_service import (
        assign_profile_to_video,
        build_media_profile_fields,
        compute_auto_compatibility,
        upsert_media_profile,
    )

    db = SessionLocal()
    videos = db.query(Video).filter(Video.id.in_([v1, v2])).all()
    fields = build_media_profile_fields(
        extension=".360",
        container_format="mov,mp4,m4a,3gp,3g2,mj2",
        video_codec="h264",
        video_profile="high",
        video_level="42",
        pixel_format="yuv420p",
        audio_codec="aac",
        audio_channels=2,
        audio_sample_rate=48000,
        width=3840,
        height=1920,
    )
    auto_status, auto_reason = compute_auto_compatibility(".360", "h264", "aac")
    profile = upsert_media_profile(db, fields, auto_status=auto_status, auto_reason=auto_reason)
    for video in videos:
        assign_profile_to_video(video, profile)
    profile.sample_video_id = videos[0].id
    db.commit()
    db.close()

    response = client.get("/api/media-profiles")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    profile_row = next((item for item in data if item["files_count"] == 2), None)
    assert profile_row is not None
    assert profile_row["sample_video"] is not None
    assert profile_row["sample_video"]["watch_url"].startswith("/watch/")


def test_library_summary_includes_media_profile_counts(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    response = client.get("/api/library/summary")
    assert response.status_code == 200
    data = response.json()
    assert "media_profiles_total" in data
    assert "media_profiles_manual_checked" in data
    assert "media_profiles_pending_manual_check" in data

