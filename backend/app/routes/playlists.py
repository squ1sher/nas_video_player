from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import (
    PlaylistAddItemsIn,
    PlaylistAddItemsOut,
    PlaylistBulkRemoveIn,
    PlaylistBulkRemoveOut,
    PlaylistContextOut,
    PlaylistCreateIn,
    PlaylistDetailOut,
    PlaylistOut,
    PlaylistReorderIn,
    PlaylistUpdateIn,
)
from app.services.playlist_service import (
    PlaylistError,
    add_videos_to_playlist,
    bulk_remove_videos_from_playlist,
    create_playlist,
    delete_playlist,
    get_playlist_detail,
    get_playlist_playback_context,
    list_playlists,
    remove_video_from_playlist,
    reorder_playlist_items,
    update_playlist,
)

router = APIRouter(prefix="/api/playlists", tags=["playlists"])


@router.get("", response_model=list[PlaylistOut])
def get_playlists(db: Session = Depends(get_db)) -> list[PlaylistOut]:
    return [PlaylistOut(**item) for item in list_playlists(db)]


@router.post("", response_model=PlaylistOut, status_code=201)
def create_playlist_route(body: PlaylistCreateIn, db: Session = Depends(get_db)) -> PlaylistOut:
    try:
        return PlaylistOut(**create_playlist(db, name=body.name, description=body.description))
    except PlaylistError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)}) from exc


@router.put("/{playlist_id}", response_model=PlaylistOut)
def update_playlist_route(playlist_id: int, body: PlaylistUpdateIn, db: Session = Depends(get_db)) -> PlaylistOut:
    try:
        return PlaylistOut(**update_playlist(db, playlist_id=playlist_id, name=body.name, description=body.description))
    except PlaylistError as exc:
        status_code = 404 if exc.code == "playlist_not_found" else 409
        raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": str(exc)}) from exc


@router.delete("/{playlist_id}")
def delete_playlist_route(playlist_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    try:
        return delete_playlist(db, playlist_id=playlist_id)
    except PlaylistError as exc:
        status_code = 404 if exc.code == "playlist_not_found" else 409
        raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": str(exc)}) from exc


@router.get("/{playlist_id}", response_model=PlaylistDetailOut)
def get_playlist_route(playlist_id: int, db: Session = Depends(get_db)) -> PlaylistDetailOut:
    try:
        return PlaylistDetailOut(**get_playlist_detail(db, playlist_id=playlist_id))
    except PlaylistError as exc:
        status_code = 404 if exc.code == "playlist_not_found" else 409
        raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": str(exc)}) from exc


@router.get("/{playlist_id}/context/{video_id}", response_model=PlaylistContextOut)
def get_playlist_context_route(
    playlist_id: int, video_id: int, db: Session = Depends(get_db)
) -> PlaylistContextOut:
    """
    Return playback context (previous / current / next) for a specific video inside a playlist.
    Order is always by playlist_items.position ASC — never by date, title, or any other key.
    Missing videos are skipped for previous/next.
    """
    try:
        return PlaylistContextOut(**get_playlist_playback_context(db, playlist_id=playlist_id, video_id=video_id))
    except PlaylistError as exc:
        status_code = 404 if exc.code in {"playlist_not_found", "video_not_in_playlist"} else 409
        raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": str(exc)}) from exc


@router.post("/{playlist_id}/items", response_model=PlaylistAddItemsOut)
def add_playlist_items_route(playlist_id: int, body: PlaylistAddItemsIn, db: Session = Depends(get_db)) -> PlaylistAddItemsOut:
    try:
        return PlaylistAddItemsOut(**add_videos_to_playlist(db, playlist_id=playlist_id, video_ids=body.video_ids))
    except PlaylistError as exc:
        status_code = 404 if exc.code == "playlist_not_found" else 409
        raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": str(exc)}) from exc


@router.delete("/{playlist_id}/items/{video_id}")
def delete_playlist_item_route(playlist_id: int, video_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    try:
        return remove_video_from_playlist(db, playlist_id=playlist_id, video_id=video_id)
    except PlaylistError as exc:
        status_code = 404 if exc.code in {"playlist_not_found", "playlist_item_not_found"} else 409
        raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": str(exc)}) from exc


@router.post("/{playlist_id}/items/reorder", response_model=PlaylistDetailOut)
def reorder_playlist_route(playlist_id: int, body: PlaylistReorderIn, db: Session = Depends(get_db)) -> PlaylistDetailOut:
    try:
        payload = reorder_playlist_items(
            db,
            playlist_id=playlist_id,
            video_ids=body.video_ids,
            ordered_pairs=[{"video_id": item.video_id, "position": item.position} for item in body.items],
        )
        return PlaylistDetailOut(**payload)
    except PlaylistError as exc:
        status_code = 404 if exc.code == "playlist_not_found" else 409
        raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": str(exc)}) from exc


@router.post("/{playlist_id}/items/remove-bulk", response_model=PlaylistBulkRemoveOut)
def bulk_remove_playlist_items_route(
    playlist_id: int, body: PlaylistBulkRemoveIn, db: Session = Depends(get_db)
) -> PlaylistBulkRemoveOut:
    try:
        result = bulk_remove_videos_from_playlist(db, playlist_id=playlist_id, video_ids=body.video_ids)
        return PlaylistBulkRemoveOut(**result)
    except PlaylistError as exc:
        status_code = 404 if exc.code == "playlist_not_found" else 409
        raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": str(exc)}) from exc


