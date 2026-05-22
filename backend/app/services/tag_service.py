from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Tag, Video, VideoTag


class TagError(ValueError):
    def __init__(self, message: str, code: str = "tag_error") -> None:
        super().__init__(message)
        self.code = code


def normalize_tag_name(name: str) -> tuple[str, str]:
    cleaned = " ".join(name.strip().split())
    if not cleaned:
        raise TagError("Tag name cannot be empty.", code="invalid_name")
    return cleaned, cleaned.lower()


def _build_path(parent: Tag | None, tag_name: str) -> tuple[str, int]:
    if parent is None:
        return tag_name, 0
    return f"{parent.path}/{tag_name}", parent.depth + 1


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_parent_exists(db: Session, parent_id: int | None) -> Tag | None:
    if parent_id is None:
        return None
    parent = db.query(Tag).filter(Tag.id == parent_id).first()
    if parent is None:
        raise TagError("Parent tag not found.", code="parent_not_found")
    return parent


def _ensure_unique_under_parent(db: Session, parent_id: int | None, normalized_name: str, exclude_tag_id: int | None = None) -> None:
    query = db.query(Tag).filter(
        Tag.normalized_name == normalized_name,
        Tag.parent_id == parent_id,
    )
    if exclude_tag_id is not None:
        query = query.filter(Tag.id != exclude_tag_id)
    if query.first() is not None:
        raise TagError("A tag with this name already exists under the selected parent.", code="duplicate_tag")


def _collect_subtree_ids(db: Session, tag_id: int) -> set[int]:
    descendants: set[int] = set()
    frontier = [tag_id]
    while frontier:
        rows = db.query(Tag.id).filter(Tag.parent_id.in_(frontier)).all()
        frontier = [row[0] for row in rows]
        descendants.update(frontier)
    return descendants


def _recompute_paths(db: Session) -> None:
    tags = db.query(Tag).order_by(Tag.id.asc()).all()
    children_by_parent: dict[int | None, list[Tag]] = defaultdict(list)
    for tag in tags:
        children_by_parent[tag.parent_id].append(tag)

    now = _now_utc()

    def walk(parent_id: int | None, parent_path: str, depth: int) -> None:
        for tag in children_by_parent.get(parent_id, []):
            path = f"{parent_path}/{tag.name}" if parent_path else tag.name
            tag.path = path
            tag.depth = depth
            tag.updated_at = now
            walk(tag.id, path, depth + 1)

    walk(None, "", 0)


def _tag_counts(db: Session) -> dict[int, int]:
    rows = db.query(VideoTag.tag_id, func.count(VideoTag.video_id)).group_by(VideoTag.tag_id).all()
    return {tag_id: count for tag_id, count in rows}


def list_tags_flat(db: Session) -> list[dict[str, object]]:
    counts = _tag_counts(db)
    tags = db.query(Tag).order_by(Tag.path.asc()).all()
    return [
        {
            "id": tag.id,
            "name": tag.name,
            "normalized_name": tag.normalized_name,
            "parent_id": tag.parent_id,
            "path": tag.path,
            "depth": tag.depth,
            "color": tag.color,
            "description": tag.description,
            "video_count": counts.get(tag.id, 0),
            "created_at": tag.created_at,
            "updated_at": tag.updated_at,
        }
        for tag in tags
    ]


def list_tags_tree(db: Session) -> list[dict[str, object]]:
    counts = _tag_counts(db)
    tags = db.query(Tag).order_by(Tag.path.asc()).all()
    node_by_id: dict[int, dict[str, object]] = {}
    roots: list[dict[str, object]] = []

    for tag in tags:
        node_by_id[tag.id] = {
            "id": tag.id,
            "name": tag.name,
            "normalized_name": tag.normalized_name,
            "parent_id": tag.parent_id,
            "path": tag.path,
            "depth": tag.depth,
            "color": tag.color,
            "description": tag.description,
            "video_count": counts.get(tag.id, 0),
            "created_at": tag.created_at,
            "updated_at": tag.updated_at,
            "children": [],
        }

    for tag in tags:
        node = node_by_id[tag.id]
        if tag.parent_id is None:
            roots.append(node)
        else:
            parent_node = node_by_id.get(tag.parent_id)
            if parent_node is not None:
                parent_node["children"].append(node)

    return roots


def create_tag(db: Session, *, name: str, parent_id: int | None, color: str | None, description: str | None) -> Tag:
    cleaned_name, normalized_name = normalize_tag_name(name)
    parent = _ensure_parent_exists(db, parent_id)
    _ensure_unique_under_parent(db, parent_id, normalized_name)
    path, depth = _build_path(parent, cleaned_name)

    tag = Tag(
        name=cleaned_name,
        normalized_name=normalized_name,
        parent_id=parent_id,
        path=path,
        depth=depth,
        color=color,
        description=description,
    )
    db.add(tag)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise TagError("A tag with this name already exists under the selected parent.", code="duplicate_tag") from exc
    db.refresh(tag)
    return tag


def update_tag(
    db: Session,
    *,
    tag_id: int,
    name: str,
    parent_id: int | None,
    color: str | None,
    description: str | None,
) -> Tag:
    tag = db.query(Tag).filter(Tag.id == tag_id).first()
    if tag is None:
        raise TagError("Tag not found.", code="tag_not_found")

    cleaned_name, normalized_name = normalize_tag_name(name)

    if parent_id == tag.id:
        raise TagError("Cannot move tag under itself.", code="invalid_parent")

    if parent_id is not None:
        descendants = _collect_subtree_ids(db, tag.id)
        if parent_id in descendants:
            raise TagError("Cannot move tag under its descendant.", code="invalid_parent")

    _ensure_parent_exists(db, parent_id)
    _ensure_unique_under_parent(db, parent_id, normalized_name, exclude_tag_id=tag.id)

    tag.name = cleaned_name
    tag.normalized_name = normalized_name
    tag.parent_id = parent_id
    tag.color = color
    tag.description = description
    tag.updated_at = _now_utc()

    _recompute_paths(db)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise TagError("A tag with this name already exists under the selected parent.", code="duplicate_tag") from exc
    db.refresh(tag)
    return tag


def delete_tag(db: Session, *, tag_id: int, force: bool = False) -> dict[str, int | bool]:
    tag = db.query(Tag).filter(Tag.id == tag_id).first()
    if tag is None:
        raise TagError("Tag not found.", code="tag_not_found")

    children_count = db.query(Tag).filter(Tag.parent_id == tag_id).count()
    if children_count > 0 and not force:
        raise TagError("Cannot delete tag with child tags.", code="tag_has_children")

    tag_ids = {tag_id}
    if force:
        tag_ids.update(_collect_subtree_ids(db, tag_id))

    removed_links = db.query(VideoTag).filter(VideoTag.tag_id.in_(tag_ids)).delete(synchronize_session=False)
    removed_tags = db.query(Tag).filter(Tag.id.in_(tag_ids)).delete(synchronize_session=False)
    db.commit()
    return {"deleted": True, "deleted_tags": removed_tags, "removed_links": removed_links}


def get_video_tags(db: Session, video_id: int) -> list[dict[str, object]]:
    video_exists = db.query(Video.id).filter(Video.id == video_id).first()
    if video_exists is None:
        raise TagError("Video not found.", code="video_not_found")

    rows = (
        db.query(Tag)
        .join(VideoTag, VideoTag.tag_id == Tag.id)
        .filter(VideoTag.video_id == video_id)
        .order_by(Tag.path.asc())
        .all()
    )
    return [
        {
            "id": tag.id,
            "name": tag.name,
            "path": tag.path,
            "parent_id": tag.parent_id,
            "color": tag.color,
        }
        for tag in rows
    ]


def assign_video_tags(db: Session, *, video_id: int, tag_ids: list[int], replace: bool) -> list[dict[str, object]]:
    video_exists = db.query(Video.id).filter(Video.id == video_id).first()
    if video_exists is None:
        raise TagError("Video not found.", code="video_not_found")

    wanted_ids = sorted({tag_id for tag_id in tag_ids})
    if wanted_ids:
        existing_ids = {
            row[0]
            for row in db.query(Tag.id).filter(Tag.id.in_(wanted_ids)).all()
        }
        missing = [tag_id for tag_id in wanted_ids if tag_id not in existing_ids]
        if missing:
            raise TagError(f"Tag not found: {missing[0]}", code="tag_not_found")

    current_ids = {
        row[0]
        for row in db.query(VideoTag.tag_id).filter(VideoTag.video_id == video_id).all()
    }

    if replace:
        remove_ids = current_ids - set(wanted_ids)
        if remove_ids:
            db.query(VideoTag).filter(
                VideoTag.video_id == video_id,
                VideoTag.tag_id.in_(remove_ids),
            ).delete(synchronize_session=False)
        add_ids = set(wanted_ids) - current_ids
    else:
        add_ids = set(wanted_ids) - current_ids

    for tag_id in sorted(add_ids):
        db.add(VideoTag(video_id=video_id, tag_id=tag_id))

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise TagError("Failed to update video tags due to a database conflict.", code="tag_conflict") from exc
    return get_video_tags(db, video_id)


def remove_video_tag(db: Session, *, video_id: int, tag_id: int) -> dict[str, bool]:
    video_exists = db.query(Video.id).filter(Video.id == video_id).first()
    if video_exists is None:
        raise TagError("Video not found.", code="video_not_found")

    db.query(VideoTag).filter(VideoTag.video_id == video_id, VideoTag.tag_id == tag_id).delete(synchronize_session=False)
    db.commit()
    return {"deleted": True}


def get_video_tags_map(db: Session, video_ids: list[int]) -> dict[int, list[dict[str, object]]]:
    if not video_ids:
        return {}

    rows = (
        db.query(VideoTag.video_id, Tag.id, Tag.name, Tag.path, Tag.color)
        .join(Tag, Tag.id == VideoTag.tag_id)
        .filter(VideoTag.video_id.in_(video_ids))
        .order_by(VideoTag.video_id.asc(), Tag.path.asc())
        .all()
    )
    tags_by_video: dict[int, list[dict[str, object]]] = defaultdict(list)
    for video_id, tag_id, name, path, color in rows:
        tags_by_video[video_id].append(
            {
                "id": tag_id,
                "name": name,
                "path": path,
                "color": color,
            }
        )
    return dict(tags_by_video)

