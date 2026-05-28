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


def _validate_no_cycles(parent_by_id: dict[int, int | None]) -> None:
    for tag_id in parent_by_id:
        seen: set[int] = set()
        current = tag_id
        while current is not None:
            if current in seen:
                raise TagError("Cannot move tag under itself or its descendant.", code="cycle_detected")
            seen.add(current)
            current = parent_by_id.get(current)


def _validate_duplicate_names_under_parent(
    tags_by_id: dict[int, Tag],
    parent_by_id: dict[int, int | None],
    normalized_name_by_id: dict[int, str] | None = None,
) -> None:
    names_by_parent: dict[int | None, set[str]] = defaultdict(set)
    for tag_id, tag in tags_by_id.items():
        parent_id = parent_by_id[tag_id]
        sibling_names = names_by_parent[parent_id]
        normalized_name = normalized_name_by_id[tag_id] if normalized_name_by_id is not None else tag.normalized_name
        if normalized_name in sibling_names:
            raise TagError(
                "A tag with this name already exists under the selected parent.",
                code="duplicate_tag_name_under_parent",
            )
        sibling_names.add(normalized_name)


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


def apply_tag_tree_moves(db: Session, *, moves: list[dict[str, object]]) -> dict[str, object]:
    tags = db.query(Tag).order_by(Tag.id.asc()).all()
    tags_by_id = {tag.id: tag for tag in tags}

    if not moves:
        return {"status": "no_changes", "updated_tags": 0, "tree": list_tags_tree(db)}

    deduped_moves: dict[int, dict[str, object]] = {}
    for move in moves:
        tag_id = int(move.get("tag_id", 0))
        new_parent_id = move.get("new_parent_id")
        if tag_id not in tags_by_id:
            raise TagError("Tag not found.", code="tag_not_found")
        if new_parent_id is not None and new_parent_id not in tags_by_id:
            raise TagError("Parent tag not found.", code="parent_not_found")
        new_name = move.get("new_name")
        deduped_moves[tag_id] = {"new_parent_id": new_parent_id, "new_name": new_name}

    parent_by_id = {tag.id: tag.parent_id for tag in tags}
    cleaned_name_by_id = {tag.id: tag.name for tag in tags}
    normalized_name_by_id = {tag.id: tag.normalized_name for tag in tags}

    for tag_id, change in deduped_moves.items():
        new_parent_id = change["new_parent_id"]
        if tag_id == new_parent_id:
            raise TagError("Cannot move tag under itself.", code="invalid_move")
        parent_by_id[tag_id] = new_parent_id

        new_name = change.get("new_name")
        if new_name is not None:
            cleaned_name, normalized_name = normalize_tag_name(str(new_name))
            cleaned_name_by_id[tag_id] = cleaned_name
            normalized_name_by_id[tag_id] = normalized_name

    _validate_no_cycles(parent_by_id)
    _validate_duplicate_names_under_parent(tags_by_id, parent_by_id, normalized_name_by_id)

    old_path_by_id = {tag.id: tag.path for tag in tags}
    old_depth_by_id = {tag.id: tag.depth for tag in tags}
    old_name_by_id = {tag.id: tag.name for tag in tags}
    changed_tag_ids = {
        tag_id
        for tag_id, change in deduped_moves.items()
        if tags_by_id[tag_id].parent_id != change["new_parent_id"] or tags_by_id[tag_id].name != cleaned_name_by_id[tag_id]
    }
    if not changed_tag_ids:
        return {"status": "no_changes", "updated_tags": 0, "tree": list_tags_tree(db)}

    now = _now_utc()
    for tag in tags:
        next_parent_id = parent_by_id[tag.id]
        next_name = cleaned_name_by_id[tag.id]
        next_normalized_name = normalized_name_by_id[tag.id]
        if tag.parent_id != next_parent_id or tag.name != next_name or tag.normalized_name != next_normalized_name:
            tag.name = next_name
            tag.normalized_name = next_normalized_name
            tag.parent_id = next_parent_id
            tag.updated_at = now

    _recompute_paths(db)

    updated_tags = 0
    for tag in tags:
        if old_path_by_id[tag.id] != tag.path or old_depth_by_id[tag.id] != tag.depth or old_name_by_id[tag.id] != tag.name or tag.id in changed_tag_ids:
            updated_tags += 1

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise TagError("Failed to update tag tree due to a database conflict.", code="tag_conflict") from exc

    return {"status": "updated", "updated_tags": updated_tags, "tree": list_tags_tree(db)}


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


def bulk_assign_tags_to_videos(db: Session, *, video_ids: list[int], tag_ids: list[int]) -> dict[str, object]:
    wanted_video_ids = sorted({video_id for video_id in video_ids})
    wanted_tag_ids = sorted({tag_id for tag_id in tag_ids})

    if not wanted_video_ids or not wanted_tag_ids:
        return {
            "videos_processed": 0,
            "tags_assigned": len(wanted_tag_ids),
            "assignments_created": 0,
            "skipped": wanted_video_ids,
            "errors": [],
        }

    existing_tag_ids = {row[0] for row in db.query(Tag.id).filter(Tag.id.in_(wanted_tag_ids)).all()}
    missing_tags = [tag_id for tag_id in wanted_tag_ids if tag_id not in existing_tag_ids]
    if missing_tags:
        raise TagError(f"Tag not found: {missing_tags[0]}", code="tag_not_found")

    existing_video_ids = {row[0] for row in db.query(Video.id).filter(Video.id.in_(wanted_video_ids)).all()}
    skipped = [video_id for video_id in wanted_video_ids if video_id not in existing_video_ids]

    if not existing_video_ids:
        return {
            "videos_processed": 0,
            "tags_assigned": len(wanted_tag_ids),
            "assignments_created": 0,
            "skipped": skipped,
            "errors": [],
        }

    existing_pairs = {
        (video_id, tag_id)
        for video_id, tag_id in (
            db.query(VideoTag.video_id, VideoTag.tag_id)
            .filter(VideoTag.video_id.in_(existing_video_ids), VideoTag.tag_id.in_(wanted_tag_ids))
            .all()
        )
    }

    created = 0
    for video_id in sorted(existing_video_ids):
        for tag_id in wanted_tag_ids:
            if (video_id, tag_id) in existing_pairs:
                continue
            db.add(VideoTag(video_id=video_id, tag_id=tag_id))
            created += 1

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise TagError("Failed to update video tags due to a database conflict.", code="tag_conflict") from exc

    return {
        "videos_processed": len(existing_video_ids),
        "tags_assigned": len(wanted_tag_ids),
        "assignments_created": created,
        "skipped": skipped,
        "errors": [],
    }


