import { Link } from "react-router-dom";

import type { UnifiedMediaItem } from "../../types/video";

export function mediaItemKey(item: UnifiedMediaItem): string {
  return `${item.type}:${item.id}`;
}

type Props = {
  item: UnifiedMediaItem;
  selectionMode?: boolean;
  selected?: boolean;
  onToggleSelect?: (item: UnifiedMediaItem) => void;
};

/** Compact media card used inside grouped/lazy media grids (video + photo). */
export function MediaCard({ item, selectionMode = false, selected = false, onToggleSelect }: Props) {
  const content = (
    <>
      <div className="thumb-wrap thumb-wrap-square">
        {item.thumbnail_url ? (
          <img
            src={item.thumbnail_url}
            alt={item.display_title}
            className="thumb"
            loading="lazy"
            onError={(e) => {
              e.currentTarget.style.visibility = "hidden";
            }}
          />
        ) : (
          <div className="thumb-fallback">No thumbnail</div>
        )}
        {item.raw_format ? (
          <span
            style={{
              position: "absolute",
              top: 6,
              left: 6,
              background: "rgba(0,0,0,0.7)",
              color: "#fff",
              fontSize: 10,
              fontWeight: 700,
              padding: "2px 6px",
              borderRadius: 4,
              letterSpacing: 0.5,
            }}
          >
            RAW
          </span>
        ) : null}
        {selectionMode ? (
          <label
            className="video-select-checkbox"
            onClick={(e) => e.stopPropagation()}
            title={selected ? "Deselect" : "Select"}
          >
            <input type="checkbox" checked={selected} onChange={() => onToggleSelect?.(item)} />
          </label>
        ) : null}
      </div>
    </>
  );

  if (selectionMode) {
    return (
      <button
        type="button"
        className={`video-card compact video-card-selection-mode${selected ? " video-card-selected" : ""}`}
        onClick={() => onToggleSelect?.(item)}
        title={item.display_title}
      >
        {content}
      </button>
    );
  }

  if (item.type === "video") {
    return (
      <Link className="video-card compact" to={`/watch/${item.id}`} title={item.display_title}>
        {content}
      </Link>
    );
  }

  return (
    <a
      className="video-card compact"
      href={`/photo/${item.id}`}
      target="_blank"
      rel="noopener noreferrer"
      title={item.display_title}
    >
      {content}
    </a>
  );
}
