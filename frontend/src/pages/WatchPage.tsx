import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { deleteVideo, fetchVideo, getDownloadUrl, getProgress } from "../api/client";
import { CompatibilityBadge } from "../components/CompatibilityBadge";
import { VideoPlayer } from "../components/VideoPlayer";
import type { VideoDetail, WatchProgress } from "../types/video";

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
  const [progress, setProgress] = useState<WatchProgress | null>(null);
  const [initialPosition, setInitialPosition] = useState<number>(0);
  const [askResume, setAskResume] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);

  useEffect(() => {
    async function load() {
      if (!id) {
        setError("Missing video id");
        setLoading(false);
        return;
      }
      try {
        setLoading(true);
        const [vid, prog] = await Promise.all([fetchVideo(id), getProgress(Number(id))]);
        setVideo(vid);
        setProgress(prog);
        // Show resume prompt if position is meaningful and not completed
        if (prog.position_seconds > 5 && !prog.completed) {
          setAskResume(true);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load video");
      } finally {
        setLoading(false);
      }
    }
    void load();
  }, [id]);

  if (loading) return <div className="page status">Loading video…</div>;
  if (error || !video) return <div className="page error">{error ?? "Video not found"}</div>;

  const handleResume = () => {
    setInitialPosition(progress?.position_seconds ?? 0);
    setAskResume(false);
  };

  const handleFromBeginning = () => {
    setInitialPosition(0);
    setAskResume(false);
  };

  const handleDelete = async () => {
    if (!video) return;
    const ok = window.confirm("Delete this video from the library? This will also try to delete the source file.");
    if (!ok) return;

    try {
      setDeleteBusy(true);
      await deleteVideo(video.id);
      window.location.href = "/";
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete video");
      setDeleteBusy(false);
    }
  };

  return (
    <div className="page watch-page">
      <div className="watch-header">
        <div className="watch-header-left">
          <a className="back-link" href="/">← Library</a>
          <h1 className="watch-title">{video.title}</h1>
        </div>
        <div className="watch-header-right">
          <CompatibilityBadge
            status={video.compatibility_status}
            reason={video.compatibility_reason}
            showTooltip
          />
          <a className="btn-secondary" href={getDownloadUrl(video.id)}>
            Download
          </a>
          <button className="btn-danger" onClick={handleDelete} disabled={deleteBusy}>
            {deleteBusy ? "Deleting..." : "Delete"}
          </button>
        </div>
      </div>

      {askResume && progress && (
        <div className="resume-banner">
          <span>Continue from {formatDuration(progress.position_seconds)}?</span>
          <button className="btn-primary" onClick={handleResume}>Resume</button>
          <button className="btn-secondary" onClick={handleFromBeginning}>Start from beginning</button>
        </div>
      )}

      <VideoPlayer video={video} initialPosition={initialPosition} />

      <div className="meta-grid">
        <div>
          <strong>Duration:</strong> {formatDuration(video.duration)}
        </div>
        <div>
          <strong>Resolution:</strong>{" "}
          {video.width && video.height ? `${video.width}×${video.height}` : "Unknown"}
        </div>
        <div>
          <strong>Video codec:</strong> {video.video_codec ?? "Unknown"}
        </div>
        <div>
          <strong>Audio codec:</strong> {video.audio_codec ?? "Unknown"}
        </div>
        <div>
          <strong>Container:</strong> {video.extension.toUpperCase()}
        </div>
        <div>
          <strong>File size:</strong> {formatSize(video.size)}
        </div>
        <div>
          <strong>Filename:</strong> {video.filename}
        </div>
        {video.folder_path && (
          <div>
            <strong>Folder:</strong> {video.folder_path}
          </div>
        )}
        {video.compatibility_reason && (
          <div className="compat-detail">
            <strong>Compatibility note:</strong> {video.compatibility_reason}
          </div>
        )}
      </div>
    </div>
  );
}
