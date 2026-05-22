from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import TagCreateIn, TagOut, TagTreeOut, TagUpdateIn
from app.services.tag_service import TagError, create_tag, delete_tag, list_tags_flat, list_tags_tree, update_tag

router = APIRouter(prefix="/api/tags", tags=["tags"])


def _to_tag_out(payload: dict[str, object]) -> TagOut:
    return TagOut(**payload)


def _to_tree(nodes: list[dict[str, object]]) -> list[TagTreeOut]:
    return [TagTreeOut(**node) for node in nodes]


@router.get("", response_model=list[TagOut])
def get_tags(db: Session = Depends(get_db)) -> list[TagOut]:
    return [_to_tag_out(item) for item in list_tags_flat(db)]


@router.get("/tree", response_model=list[TagTreeOut])
def get_tag_tree(db: Session = Depends(get_db)) -> list[TagTreeOut]:
    return _to_tree(list_tags_tree(db))


@router.post("", response_model=TagOut, status_code=201)
def create_tag_route(body: TagCreateIn, db: Session = Depends(get_db)) -> TagOut:
    try:
        tag = create_tag(
            db,
            name=body.name,
            parent_id=body.parent_id,
            color=body.color,
            description=body.description,
        )
        return _to_tag_out(
            {
                "id": tag.id,
                "name": tag.name,
                "normalized_name": tag.normalized_name,
                "parent_id": tag.parent_id,
                "path": tag.path,
                "depth": tag.depth,
                "color": tag.color,
                "description": tag.description,
                "video_count": 0,
                "created_at": tag.created_at,
                "updated_at": tag.updated_at,
            }
        )
    except TagError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)}) from exc


@router.put("/{tag_id}", response_model=TagOut)
def update_tag_route(tag_id: int, body: TagUpdateIn, db: Session = Depends(get_db)) -> TagOut:
    try:
        tag = update_tag(
            db,
            tag_id=tag_id,
            name=body.name,
            parent_id=body.parent_id,
            color=body.color,
            description=body.description,
        )
        return _to_tag_out(
            {
                "id": tag.id,
                "name": tag.name,
                "normalized_name": tag.normalized_name,
                "parent_id": tag.parent_id,
                "path": tag.path,
                "depth": tag.depth,
                "color": tag.color,
                "description": tag.description,
                "video_count": 0,
                "created_at": tag.created_at,
                "updated_at": tag.updated_at,
            }
        )
    except TagError as exc:
        status_code = 404 if exc.code == "tag_not_found" else 409
        raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": str(exc)}) from exc


@router.delete("/{tag_id}")
def delete_tag_route(
    tag_id: int,
    force: bool = Query(False),
    db: Session = Depends(get_db),
) -> dict[str, int | bool]:
    try:
        return delete_tag(db, tag_id=tag_id, force=force)
    except TagError as exc:
        status_code = 404 if exc.code == "tag_not_found" else 409
        raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": str(exc)}) from exc

