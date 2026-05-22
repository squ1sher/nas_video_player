import type { VideoTag, VideoTagLite } from "../../types/video";

type TagLike = VideoTag | VideoTagLite;

type Props = {
  tag: TagLike;
  removable?: boolean;
  onRemove?: (tagId: number) => void;
};

export function TagChip({ tag, removable = false, onRemove }: Props) {
  return (
    <span className="tag-chip" title={tag.path}>
      <span className="tag-chip-label">{tag.path}</span>
      {removable && onRemove && (
        <button
          type="button"
          className="tag-chip-remove"
          onClick={() => onRemove(tag.id)}
          aria-label={`Remove tag ${tag.path}`}
        >
          x
        </button>
      )}
    </span>
  );
}

