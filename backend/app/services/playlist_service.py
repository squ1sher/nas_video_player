from __future__ import annotations

from datetime import datetime, timezone
from typing import cast

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import LibraryRoot, Playlist, PlaylistItem, Video
from app.services.tag_service import get_video_tags_map


class PlaylistError(ValueError):
    def __init__(self, message: str, code: str = "playlist_error") -> None:
        super().__init__(message)
        self.code = code


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _clean_name(name: str) -> str:
    cleaned = " ".join(name.strip().split())
    if not cleaned:
        raise PlaylistError("Playlist name is required.", code="invalid_name")
    return cleaned


def _get_playlist_or_404(db: Session, playlist_id: int) -> Playlist:
    playlist = db.query(Playlist).filter(Playlist.id == playlist_id).first()
    if playlist is None:
        raise PlaylistError("Playlist not found.", code="playlist_not_found")
    return cast(Playlist, playlist)


def _item_count_by_playlist(db: Session) -> dict[int, int]:
    rows = db.query(PlaylistItem.playlist_id, func.count(PlaylistItem.id)).group_by(PlaylistItem.playlist_id).all()
    return {playlist_id: count for playlist_id, count in rows}


def _normalize_playlist_positions(db: Session, playlist_id: int) -> int:
    items = (
        db.query(PlaylistItem)
        .filter(PlaylistItem.playlist_id == playlist_id)
        .order_by(PlaylistItem.position.asc(), PlaylistItem.id.asc())
        .all()
    )
    changed = 0
    for idx, item in enumerate(items, start=1):
        if item.position != idx:
            item.position = idx
            changed += 1
    return changed


def _playlist_video_payload(
    videos_by_id: dict[int, Video],
    video_id: int,
    tags_by_video: dict[int, list[dict[str, object]]],
    library_root_names: dict[int, str] | None = None,
) -> dict[str, object]:
    video = videos_by_id.get(video_id)
    if video is None:
        return {
            "id": video_id,
            "display_title": f"Unavailable video #{video_id}",
            "thumbnail_url": None,
            "duration": None,
            "availability_status": "missing",
            "tags": [],
            "size": 0,
            "filename": "",
            "folder_path": None,
            "library_root_id": None,
            "library_root_name": None,
            "file_modified_at": None,
            "created_at": None,
            "indexed_at": None,
        }

    thumb_url = f"/api/videos/{video.id}/thumbnail" if video.thumbnail_path else None
    file_modified_at = datetime.fromtimestamp(video.modified_ts, tz=timezone.utc) if video.modified_ts else None
    root_id = int(video.library_root_id) if video.library_root_id is not None else None
    root_name = (library_root_names or {}).get(root_id) if root_id is not None else None
    return {
        "id": video.id,
        "display_title": video.title,
        "thumbnail_url": thumb_url,
        "duration": video.duration,
        "availability_status": video.availability_status,
        "tags": tags_by_video.get(video.id, []),
        "size": video.size,
        "filename": video.filename,
        "folder_path": video.folder_path,
        "library_root_id": root_id,
        "library_root_name": root_name,
        "file_modified_at": file_modified_at,
        "created_at": video.created_at,
        "indexed_at": video.indexed_at,
    }


def list_playlists(db: Session) -> list[dict[str, object]]:
    item_count = _item_count_by_playlist(db)
    playlists = db.query(Playlist).order_by(Playlist.updated_at.desc(), Playlist.id.desc()).all()
    return [
        {
            "id": playlist.id,
            "name": playlist.name,
            "description": playlist.description,
            "item_count": item_count.get(int(playlist.id), 0),
            "created_at": playlist.created_at,
            "updated_at": playlist.updated_at,
        }
        for playlist in playlists
    ]


def create_playlist(db: Session, *, name: str, description: str | None = None) -> dict[str, object]:
    playlist = Playlist(name=_clean_name(name), description=description)
    db.add(playlist)
    db.commit()
    db.refresh(playlist)
    return {
        "id": playlist.id,
        "name": playlist.name,
        "description": playlist.description,
        "item_count": 0,
        "created_at": playlist.created_at,
        "updated_at": playlist.updated_at,
    }


def update_playlist(db: Session, *, playlist_id: int, name: str, description: str | None = None) -> dict[str, object]:
    playlist = _get_playlist_or_404(db, playlist_id)
    playlist.name = _clean_name(name)
    playlist.description = description
    playlist.updated_at = _now_utc()
    db.commit()
    db.refresh(playlist)

    item_count = db.query(PlaylistItem.id).filter(PlaylistItem.playlist_id == playlist_id).count()
    return {
        "id": playlist.id,
        "name": playlist.name,
        "description": playlist.description,
        "item_count": item_count,
        "created_at": playlist.created_at,
        "updated_at": playlist.updated_at,
    }


def delete_playlist(db: Session, *, playlist_id: int) -> dict[str, bool]:
    playlist = _get_playlist_or_404(db, playlist_id)
    db.delete(playlist)
    db.commit()
    return {"deleted": True}


def get_playlist_detail(db: Session, *, playlist_id: int) -> dict[str, object]:
    playlist = _get_playlist_or_404(db, playlist_id)
    items = (
        db.query(PlaylistItem)
        .filter(PlaylistItem.playlist_id == playlist_id)
        .order_by(PlaylistItem.position.asc(), PlaylistItem.id.asc())
        .all()
    )

    video_ids = [int(item.video_id) for item in items]
    videos = db.query(Video).filter(Video.id.in_(video_ids)).all() if video_ids else []
    videos_by_id = {int(video.id): video for video in videos}
    tags_by_video = get_video_tags_map(db, [int(video.id) for video in videos]) if videos else {}

    # Fetch library root names for all relevant root ids
    root_ids = {int(v.library_root_id) for v in videos if v.library_root_id is not None}
    library_root_names: dict[int, str] = {}
    if root_ids:
        roots = db.query(LibraryRoot).filter(LibraryRoot.id.in_(root_ids)).all()
        library_root_names = {int(r.id): r.name for r in roots}

    payload_items = [
        {
            "id": int(item.video_id),
            "playlist_item_id": item.id,
            "position": item.position,
            "video": _playlist_video_payload(videos_by_id, int(item.video_id), tags_by_video, library_root_names),
        }
        for item in items
    ]

    return {
        "id": playlist.id,
        "name": playlist.name,
        "description": playlist.description,
        "item_count": len(items),
        "created_at": playlist.created_at,
        "updated_at": playlist.updated_at,
        "items": payload_items,
    }


def add_videos_to_playlist(db: Session, *, playlist_id: int, video_ids: list[int]) -> dict[str, object]:
    _get_playlist_or_404(db, playlist_id)

    wanted_video_ids = []
    seen: set[int] = set()
    for video_id in video_ids:
        if video_id <= 0 or video_id in seen:
            continue
        seen.add(video_id)
        wanted_video_ids.append(video_id)

    if not wanted_video_ids:
        item_count = db.query(PlaylistItem.id).filter(PlaylistItem.playlist_id == playlist_id).count()
        return {
            "playlist_id": playlist_id,
            "added": [],
            "skipped_existing": [],
            "invalid": [],
            "item_count": item_count,
        }

    existing_videos = {
        row[0]
        for row in db.query(Video.id).filter(Video.id.in_(wanted_video_ids)).all()
    }
    invalid = [video_id for video_id in wanted_video_ids if video_id not in existing_videos]

    existing_playlist_videos = {
        row[0]
        for row in db.query(PlaylistItem.video_id).filter(PlaylistItem.playlist_id == playlist_id).all()
    }

    skipped_existing: list[int] = []
    to_add: list[int] = []
    for video_id in wanted_video_ids:
        if video_id not in existing_videos:
            continue
        if video_id in existing_playlist_videos:
            skipped_existing.append(video_id)
            continue
        to_add.append(video_id)

    max_position = db.query(func.max(PlaylistItem.position)).filter(PlaylistItem.playlist_id == playlist_id).scalar() or 0
    for offset, video_id in enumerate(to_add, start=1):
        db.add(
            PlaylistItem(
                playlist_id=playlist_id,
                video_id=video_id,
                position=max_position + offset,
            )
        )

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise PlaylistError("Failed to add playlist items due to a database conflict.", code="playlist_conflict") from exc

    item_count = db.query(PlaylistItem.id).filter(PlaylistItem.playlist_id == playlist_id).count()
    return {
        "playlist_id": playlist_id,
        "added": to_add,
        "skipped_existing": skipped_existing,
        "invalid": invalid,
        "item_count": item_count,
    }


def remove_video_from_playlist(db: Session, *, playlist_id: int, video_id: int) -> dict[str, bool]:
    _get_playlist_or_404(db, playlist_id)

    deleted = (
        db.query(PlaylistItem)
        .filter(PlaylistItem.playlist_id == playlist_id, PlaylistItem.video_id == video_id)
        .delete(synchronize_session=False)
    )
    if deleted == 0:
        raise PlaylistError("Video is not in playlist.", code="playlist_item_not_found")

    _normalize_playlist_positions(db, playlist_id)
    playlist = db.query(Playlist).filter(Playlist.id == playlist_id).first()
    if playlist is not None:
        playlist.updated_at = _now_utc()
    db.commit()
    return {"deleted": True}


def reorder_playlist_items(
    db: Session,
    *,
    playlist_id: int,
    video_ids: list[int] | None = None,
    ordered_pairs: list[dict[str, int]] | None = None,
) -> dict[str, object]:
    _get_playlist_or_404(db, playlist_id)

    if video_ids is None and ordered_pairs is None:
        raise PlaylistError("Provide video_ids or items for reorder.", code="invalid_reorder")

    current_items = db.query(PlaylistItem).filter(PlaylistItem.playlist_id == playlist_id).all()
    current_video_ids = {int(item.video_id) for item in current_items}

    if video_ids is None:
        # Accept {items:[{video_id, position}]} and sort it by requested position.
        sorted_pairs = sorted(ordered_pairs or [], key=lambda row: int(row.get("position", 0)))
        video_ids = [int(row.get("video_id", 0)) for row in sorted_pairs]

    deduped_video_ids: list[int] = []
    seen: set[int] = set()
    for video_id in video_ids:
        if video_id <= 0 or video_id in seen:
            continue
        seen.add(video_id)
        deduped_video_ids.append(video_id)

    if set(deduped_video_ids) != current_video_ids or len(deduped_video_ids) != len(current_items):
        raise PlaylistError("Reorder payload must include all playlist videos exactly once.", code="invalid_reorder")

    item_by_video_id = {int(item.video_id): item for item in current_items}
    for position, video_id in enumerate(deduped_video_ids, start=1):
        item_by_video_id[video_id].position = position

    playlist = db.query(Playlist).filter(Playlist.id == playlist_id).first()
    if playlist is not None:
        playlist.updated_at = _now_utc()

    db.commit()
    return get_playlist_detail(db, playlist_id=playlist_id)


def bulk_remove_videos_from_playlist(db: Session, *, playlist_id: int, video_ids: list[int]) -> dict[str, object]:
    _get_playlist_or_404(db, playlist_id)

    if not video_ids:
        item_count = db.query(PlaylistItem.id).filter(PlaylistItem.playlist_id == playlist_id).count()
        return {"removed": [], "not_found": [], "item_count": item_count}

    existing_video_ids_in_playlist = {
        int(row[0])
        for row in db.query(PlaylistItem.video_id).filter(
            PlaylistItem.playlist_id == playlist_id,
            PlaylistItem.video_id.in_(video_ids),
        ).all()
    }

    to_remove = [vid for vid in video_ids if vid in existing_video_ids_in_playlist]
    not_found = [vid for vid in video_ids if vid not in existing_video_ids_in_playlist]

    if to_remove:
        db.query(PlaylistItem).filter(
            PlaylistItem.playlist_id == playlist_id,
            PlaylistItem.video_id.in_(to_remove),
        ).delete(synchronize_session=False)
        _normalize_playlist_positions(db, playlist_id)
        playlist = db.query(Playlist).filter(Playlist.id == playlist_id).first()
        if playlist is not None:
            playlist.updated_at = _now_utc()
        db.commit()

    item_count = db.query(PlaylistItem.id).filter(PlaylistItem.playlist_id == playlist_id).count()
    return {"removed": to_remove, "not_found": not_found, "item_count": item_count}


def remove_video_from_all_playlists(db: Session, *, video_id: int) -> None:
    playlist_ids: list[int] = [
        int(row[0])
        for row in db.query(PlaylistItem.playlist_id)
        .filter(PlaylistItem.video_id == video_id)
        .distinct()
        .all()
    ]
    if not playlist_ids:
        return

    db.query(PlaylistItem).filter(PlaylistItem.video_id == video_id).delete(synchronize_session=False)
    touched_at = _now_utc()
    for playlist_id in playlist_ids:
        _normalize_playlist_positions(db, playlist_id)
        playlist = db.query(Playlist).filter(Playlist.id == playlist_id).first()
        if playlist is not None:
            playlist.updated_at = touched_at


