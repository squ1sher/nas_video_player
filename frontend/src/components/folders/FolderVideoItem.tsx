import type { VideoListItem, WatchProgress } from "../../types/video";
import { CompatibilityBadge } from "../CompatibilityBadge";

type Props = {
  video: VideoListItem;
  progress?: WatchProgress | null;
};

function formatDuration(seconds: number | null): string {
  if (!seconds) return "Unknown";
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

export function FolderVideoItem({ video, progress }: Props) {
  const progressPct = progress && progress.position_seconds > 0 ? Math.min(100, progress.percent_watched) : 0;
  return (
    <a className="folder-video-item" href={`/watch/${video.id}`} target="_blank" rel="noopener noreferrer">
      <div className="folder-video-thumb-wrap">
        {video.thumbnail_url ? (
          <img src={video.thumbnail_url} alt={video.title} className="folder-video-thumb" loading="lazy" />
        ) : (
          <div className="folder-video-thumb folder-video-thumb-placeholder">No Thumbnail</div>
        )}
        {progressPct > 0 && (
          <div className="progress-bar-wrap">
            <div className="progress-bar" style={{ width: `${progressPct}%` }} />
          </div>
        )}
      </div>
      <div className="folder-video-body">
        <strong className="folder-video-title">{video.title}</strong>
        <div className="folder-video-meta-row">
          <span>{formatDuration(video.duration)}</span>
          <span>{video.extension.toUpperCase()}</span>
          <span>{formatSize(video.size)}</span>
        </div>
      </div>
      <CompatibilityBadge status={video.effective_compatibility_status ?? video.compatibility_status} />
    </a>
  );
}

