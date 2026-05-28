import type { VideoListItem, WatchProgress } from "../types/video";

type Props = {
  video: VideoListItem;
  progress?: WatchProgress | null;
  selectionMode?: boolean;
  selected?: boolean;
  onToggleSelect?: (videoId: number) => void;
  playlistId?: number;
};


export function VideoCard({
  video,
  progress,
  selectionMode = false,
  selected = false,
  onToggleSelect,
  playlistId,
}: Props) {
  void progress;

  const cardClassName = `video-card video-card-minimal${selected ? " video-card-selected" : ""}${
    selectionMode ? " video-card-selection-mode" : ""
  }`;

  const handleToggle = () => {
    onToggleSelect?.(video.id);
  };

  const watchHref = playlistId
    ? `/watch/${video.id}?playlist_id=${playlistId}`
    : `/watch/${video.id}`;

  const content = (
    <>
      <div className="thumb-wrap">
        {video.thumbnail_url ? (
          <img src={video.thumbnail_url} alt={video.title} className="thumb" loading="lazy" decoding="async" />
        ) : (
          <div className="thumb placeholder">No Thumbnail</div>
        )}

        {selectionMode ? (
          <label
            className="video-select-checkbox"
            onClick={(event) => event.stopPropagation()}
            title={selected ? "Deselect video" : "Select video"}
          >
            <input type="checkbox" checked={selected} onChange={handleToggle} />
          </label>
        ) : null}

        <div className="thumb-title-overlay" aria-hidden="true">
          {video.tags.length > 0 ? (
            <div className="thumb-tags-row">
              {video.tags.map((tag) => (
                <span key={tag.id} className="thumb-tag-chip" title={tag.path}>{tag.path}</span>
              ))}
            </div>
          ) : null}
          <span className="thumb-title-text">{video.title}</span>
        </div>
      </div>
    </>
  );

  if (selectionMode) {
    return (
      <button type="button" className={cardClassName} onClick={handleToggle} title={video.title}>
        {content}
      </button>
    );
  }

  return (
    <a
      className={cardClassName}
      href={watchHref}
      target="_blank"
      rel="noopener noreferrer"
      title={video.title}
    >
      {content}
    </a>
  );
}
