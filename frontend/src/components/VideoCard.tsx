import type { VideoListItem, WatchProgress } from "../types/video";

type Props = {
  video: VideoListItem;
  progress?: WatchProgress | null;
};


export function VideoCard({ video, progress }: Props) {
  void progress;

  return (
    <a
      className="video-card video-card-minimal"
      href={`/watch/${video.id}`}
      target="_blank"
      rel="noopener noreferrer"
      title={video.title}
    >
      <div className="thumb-wrap">
        {video.thumbnail_url ? (
          <img src={video.thumbnail_url} alt={video.title} className="thumb" loading="lazy" decoding="async" />
        ) : (
          <div className="thumb placeholder">No Thumbnail</div>
        )}
        <div className="thumb-title-overlay" aria-hidden="true">
          <span className="thumb-title-text">{video.title}</span>
        </div>
      </div>
    </a>
  );
}
