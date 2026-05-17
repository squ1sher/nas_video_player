import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import {
  deleteVideo,
  fetchVideo,
  getPlaybackSource,
  getVideoHlsStatus,
  getDownloadUrl,
  getProgress,
  prepareVideoHls,
  regenerateThumbnail,
  reprobeVideo,
} from "../api/client";
import { CompatibilityBadge } from "../components/CompatibilityBadge";
import { VideoPlayer } from "../components/VideoPlayer";
import type { HlsVideoStatus, PlaybackSource, VideoDetail, WatchProgress } from "../types/video";

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
  const [reprobeBusy, setReprobeBusy] = useState(false);
  const [thumbnailBusy, setThumbnailBusy] = useState(false);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [playbackSource, setPlaybackSource] = useState<PlaybackSource | null>(null);
  const [hlsStatus, setHlsStatus] = useState<HlsVideoStatus | null>(null);
  const [hlsBusy, setHlsBusy] = useState(false);
  const [selectedQuality, setSelectedQuality] = useState("auto");
  const [playerQualities, setPlayerQualities] = useState<string[]>([]);

  const loadPlaybackData = useCallback(async (videoId: number) => {
    const [source, status] = await Promise.all([getPlaybackSource(videoId), getVideoHlsStatus(videoId)]);
    setPlaybackSource(source);
    setHlsStatus(status);
  }, []);

  useEffect(() => {
    async function load() {
      if (!id) {
        setError("Missing video id");
        setLoading(false);
        return;
      }
      try {
        setLoading(true);
        const numericId = Number(id);
        const [vid, prog] = await Promise.all([fetchVideo(id), getProgress(numericId)]);
        setVideo(vid);
        setProgress(prog);
        await loadPlaybackData(numericId);
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
  }, [id, loadPlaybackData]);

  useEffect(() => {
    if (!video) return;
    if (hlsStatus?.status !== "running" && hlsStatus?.status !== "pending") return;

    const timer = setInterval(async () => {
      try {
        const status = await getVideoHlsStatus(video.id);
        setHlsStatus(status);
      } catch {
        // non-critical polling failure
      }
    }, 2000);

    return () => clearInterval(timer);
  }, [video, hlsStatus?.status]);

  const qualityOptions = useMemo(() => {
    if (!playbackSource) return [];
    if (playbackSource.source_type === "hls") {
      const fromPlayer = playerQualities.length > 0 ? playerQualities : playbackSource.available_qualities;
      return fromPlayer;
    }
    return ["original"];
  }, [playbackSource, playerQualities]);

  useEffect(() => {
    if (!playbackSource) return;
    if (playbackSource.source_type === "hls") {
      setSelectedQuality((prev) => (prev === "original" ? "auto" : prev));
      return;
    }
    setSelectedQuality("original");
  }, [playbackSource]);

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

  const handleReprobe = async () => {
    if (!video) return;
    try {
      setActionMessage(null);
      setReprobeBusy(true);
      const updated = await reprobeVideo(video.id);
      setVideo(updated);
      setActionMessage("Metadata probe completed.");
    } catch (err) {
      setActionMessage(err instanceof Error ? err.message : "Failed to re-probe metadata");
    } finally {
      setReprobeBusy(false);
    }
  };

  const handleRegenerateThumbnail = async () => {
    if (!video) return;
    try {
      setActionMessage(null);
      setThumbnailBusy(true);
      const updated = await regenerateThumbnail(video.id);
      setVideo(updated);
      setActionMessage(updated.thumbnail_status === "generated" ? "Thumbnail regenerated." : "Thumbnail regeneration failed.");
    } catch (err) {
      setActionMessage(err instanceof Error ? err.message : "Failed to regenerate thumbnail");
    } finally {
      setThumbnailBusy(false);
    }
  };

  const handlePrepareHls = async () => {
    if (!video) return;
    try {
      setHlsBusy(true);
      setActionMessage(null);
      await prepareVideoHls(video.id, { force: false, qualities: ["480p", "720p", "1080p"] });
      const status = await getVideoHlsStatus(video.id);
      setHlsStatus(status);
      setActionMessage("Preparing HLS...");
    } catch (err) {
      setActionMessage(err instanceof Error ? err.message : "Failed to start HLS preparation");
    } finally {
      setHlsBusy(false);
    }
  };

  const handleUseHls = async () => {
    if (!video) return;
    try {
      await loadPlaybackData(video.id);
      setActionMessage("HLS ready. Switched playback source to HLS.");
    } catch (err) {
      setActionMessage(err instanceof Error ? err.message : "Failed to load HLS playback source");
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
          <button className="btn-secondary" onClick={handleReprobe} disabled={reprobeBusy || thumbnailBusy}>
            {reprobeBusy ? "Re-probing..." : "Re-probe metadata"}
          </button>
          <button className="btn-secondary" onClick={handleRegenerateThumbnail} disabled={thumbnailBusy || reprobeBusy}>
            {thumbnailBusy ? "Regenerating..." : "Regenerate thumbnail"}
          </button>
          <button className="btn-danger" onClick={handleDelete} disabled={deleteBusy}>
            {deleteBusy ? "Deleting..." : "Delete"}
          </button>
        </div>
      </div>

      {actionMessage && <div className="notice">{actionMessage}</div>}

      <div className="diagnostics-section">
        <div className="diagnostics-section-header">
          <h3>Playback Source</h3>
        </div>
        <p><strong>Source:</strong> {playbackSource?.source_type ?? "loading"}</p>
        <p><strong>Reason:</strong> {playbackSource?.reason ?? "Loading playback source..."}</p>
        <p>
          <strong>HLS status:</strong> {hlsStatus?.status ?? "idle"}
          {hlsStatus?.current_quality ? ` (${hlsStatus.current_quality})` : ""}
          {hlsStatus?.progress_percent !== null && hlsStatus?.progress_percent !== undefined
            ? ` - ${Math.round(hlsStatus.progress_percent)}%`
            : ""}
        </p>
        {hlsStatus?.status === "completed" && playbackSource?.source_type !== "hls" && (
          <p className="card-warning">HLS ready. Click "Use HLS" to switch playback source.</p>
        )}
        {hlsStatus?.error_message && <p className="card-warning">{hlsStatus.error_message}</p>}
        <div className="media-profiles-toolbar">
          <label>
            Quality
            <select
              value={selectedQuality}
              onChange={(event) => setSelectedQuality(event.target.value)}
              disabled={qualityOptions.length === 0 || playbackSource?.source_type === "none"}
            >
              {qualityOptions.map((quality) => (
                <option key={quality} value={quality}>{quality}</option>
              ))}
            </select>
          </label>
          <button className="btn-secondary" onClick={handlePrepareHls} disabled={hlsBusy || hlsStatus?.status === "running"}>
            {hlsStatus?.status === "running" ? "Preparing HLS..." : "Prepare HLS"}
          </button>
          {hlsStatus?.status === "completed" && playbackSource?.source_type !== "hls" && (
            <button className="btn-secondary" onClick={handleUseHls}>Use HLS</button>
          )}
          {playbackSource?.source_type === "hls" && <span className="diagnostics-hint">HLS ready</span>}
        </div>
      </div>

      {askResume && progress && (
        <div className="resume-banner">
          <span>Continue from {formatDuration(progress.position_seconds)}?</span>
          <button className="btn-primary" onClick={handleResume}>Resume</button>
          <button className="btn-secondary" onClick={handleFromBeginning}>Start from beginning</button>
        </div>
      )}

      <VideoPlayer
        video={video}
        sourceType={playbackSource?.source_type ?? "none"}
        streamUrl={playbackSource?.stream_url ?? null}
        selectedQuality={selectedQuality}
        onAvailableQualities={setPlayerQualities}
        initialPosition={initialPosition}
      />

      {video.media_status === "probe_failed_possible_video" && (
        <div className="notice">
          Could not read metadata. This may be an unsupported or damaged media file.
        </div>
      )}

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
          <strong>Pixel format:</strong> {video.pixel_format ?? "Unknown"}
        </div>
        <div>
          <strong>Audio codec:</strong> {video.audio_codec ?? "Unknown"}
        </div>
        <div>
          <strong>Container:</strong> {video.extension.toUpperCase()}
        </div>
        <div>
          <strong>Container format:</strong> {video.container_format ?? "Unknown"}
        </div>
        <div>
          <strong>Media status:</strong> {video.media_status ?? "Unknown"}
        </div>
        <div>
          <strong>Probe status:</strong> {video.probe_status ?? "Unknown"}
        </div>
        <div>
          <strong>Compatibility:</strong> {video.compatibility_status ?? "Unknown"}
        </div>
        <div>
          <strong>Auto guess:</strong> {video.auto_compatibility_status ?? "Unknown"}
        </div>
        <div>
          <strong>Effective status:</strong> {video.effective_compatibility_status ?? "Unknown"}
        </div>
        <div>
          <strong>Source:</strong> {video.compatibility_source ?? "unknown"}
        </div>
        <div>
          <strong>Manual profile status:</strong> {video.manual_playback_status ?? "not set"}
        </div>
        <div>
          <strong>Thumbnail status:</strong> {video.thumbnail_status ?? "Unknown"}
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
        {video.probe_error && (
          <div className="compat-detail">
            <strong>Probe error:</strong> {video.probe_error}
          </div>
        )}
        {video.thumbnail_error && (
          <div className="compat-detail">
            <strong>Thumbnail error:</strong> {video.thumbnail_error}
          </div>
        )}
      </div>
    </div>
  );
}
