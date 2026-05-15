import { Link } from "react-router-dom";
import type { VideoListItem } from "../types/video";

type Props = {
  video: VideoListItem;
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

export function VideoCard({ video }: Props) {
  const resolution = video.width && video.height ? `${video.width}x${video.height}` : "Unknown";

  return (
    <Link className="video-card" to={`/watch/${video.id}`}>
      <div className="thumb-wrap">
        {video.thumbnail_url ? (
          <img src={video.thumbnail_url} alt={video.title} className="thumb" loading="lazy" />
        ) : (
          <div className="thumb placeholder">No Thumbnail</div>
        )}
      </div>
      <div className="video-card-body">
        <h3>{video.title}</h3>
        <p>{formatDuration(video.duration)}</p>
        <p>{resolution}</p>
        <p>{video.extension.toUpperCase()} - {formatSize(video.size)}</p>
      </div>
    </Link>
  );
}

