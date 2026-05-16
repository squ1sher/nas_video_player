import type { VideoListItem, WatchProgress } from "../types/video";
import { CompatibilityBadge } from "./CompatibilityBadge";

type Props = {
  video: VideoListItem;
  progress?: WatchProgress | null;
};

function formatDuration(seconds: number | null): string {
  if (!seconds) return "Unknown duration";
  const total = Math.floor(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h > 0
    ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
    : `${m}:${String(s).padStart(2, "0")}`;
}

function formatSize(bytes: number): string {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

export function VideoCard({ video, progress }: Props) {
  const resolution = video.width && video.height ? `${video.width}x${video.height}` : null;
  const progressPct = progress && progress.position_seconds > 0 ? Math.min(100, progress.percent_watched) : 0;

  return (
    <a
      className="video-card"
      href={`/watch/${video.id}`}
      target="_blank"
      rel="noopener noreferrer"
    >
      <div className="thumb-wrap">
        {video.thumbnail_url ? (
          <img src={video.thumbnail_url} alt={video.title} className="thumb" loading="lazy" />
        ) : (
          <div className="thumb placeholder">No Thumbnail</div>
        )}
        <div className="thumb-overlay">
          <CompatibilityBadge status={video.compatibility_status} reason={video.compatibility_reason} showTooltip />
        </div>
        {progressPct > 0 && (
          <div className="progress-bar-wrap">
            <div className="progress-bar" style={{ width: `${progressPct}%` }} />
          </div>
        )}
      </div>
      <div className="video-card-body">
        <h3 className="card-title">{video.title}</h3>
        <p className="card-meta">{formatDuration(video.duration)}</p>
        {resolution && <p className="card-meta">{resolution}</p>}
        <p className="card-meta">
          {video.extension.toUpperCase()} &mdash; {formatSize(video.size)}
        </p>
        {progress && progress.position_seconds > 0 && !progress.completed && (
          <p className="card-resume">
            Resume from {formatDuration(progress.position_seconds)}
          </p>
        )}
      </div>
    </a>
  );
}
