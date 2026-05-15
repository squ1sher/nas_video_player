import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { fetchVideo } from "../api/client";
import { VideoPlayer } from "../components/VideoPlayer";
import type { VideoDetail } from "../types/video";

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

export function WatchPage() {
  const { id } = useParams();
  const [video, setVideo] = useState<VideoDetail | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [playerError, setPlayerError] = useState<string | null>(null);

  useEffect(() => {
    async function loadVideo() {
      if (!id) {
        setError("Missing video id");
        setLoading(false);
        return;
      }

      try {
        setLoading(true);
        const data = await fetchVideo(id);
        setVideo(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load video");
      } finally {
        setLoading(false);
      }
    }

    void loadVideo();
  }, [id]);

  if (loading) return <div className="page status">Loading video...</div>;
  if (error || !video) return <div className="page error">{error || "Video not found"}</div>;

  return (
    <div className="page">
      <div className="watch-header">
        <Link className="back-link" to="/">
          Back to library
        </Link>
        <h1>{video.title}</h1>
      </div>

      <VideoPlayer videoId={video.id} onError={() => setPlayerError("Video failed to load in browser")} />
      {playerError && <div className="error">{playerError}</div>}

      <div className="meta-grid">
        <div>
          <strong>Duration:</strong> {formatDuration(video.duration)}
        </div>
        <div>
          <strong>Resolution:</strong> {video.width && video.height ? `${video.width}x${video.height}` : "Unknown"}
        </div>
        <div>
          <strong>Video codec:</strong> {video.video_codec || "Unknown"}
        </div>
        <div>
          <strong>Audio codec:</strong> {video.audio_codec || "Unknown"}
        </div>
        <div>
          <strong>File size:</strong> {formatSize(video.size)}
        </div>
        <div>
          <strong>Filename:</strong> {video.filename}
        </div>
      </div>
    </div>
  );
}

