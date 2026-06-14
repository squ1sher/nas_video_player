import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  deleteVideo,
  fetchVideo,
  getPlaylistContext,
  getPlaybackSource,
  getVideoHlsStatus,
  getDownloadUrl,
  getProgress,
  prepareVideoHls,
  regenerateThumbnail,
  reprobeVideo,
} from "../api/client";
import { CompatibilityBadge } from "../components/CompatibilityBadge";
import { VideoTagsPanel } from "../components/tags/VideoTagsPanel";
import { VideoPlayer } from "../components/VideoPlayer";
import type { VideoTag } from "../types/video";
import type {
  HlsVideoStatus,
  PlaybackSource,
  PlaylistContext,
  PlaylistContextItem,
  StoredPlaylistNav,
  VideoDetail,
  WatchProgress,
} from "../types/video";

// ─── Stored-nav helpers ───────────────────────────────────────────────────────

const STORED_NAV_TTL_MS = 3_600_000; // 1 hour

function loadStoredNav(playlistId: number): StoredPlaylistNav | null {
  try {
    const raw = sessionStorage.getItem(`playlist_nav_${playlistId}`);
    if (!raw) return null;
    const data = JSON.parse(raw) as StoredPlaylistNav;
    if (!Array.isArray(data?.sequence) || data.sequence.length === 0) return null;
    if (Date.now() - (data.timestamp ?? 0) > STORED_NAV_TTL_MS) return null;
    return data;
  } catch {
    return null;
  }
}

function buildContextFromNav(nav: StoredPlaylistNav, videoId: number): PlaylistContext | null {
  const { sequence, playlist_id, playlist_name } = nav;
  const currentIdx = sequence.findIndex((item) => item.video_id === videoId);
  if (currentIdx === -1) return null;

  const isPlayable = (item: PlaylistContextItem) => item.availability_status !== "missing";

  let prev: PlaylistContextItem | null = null;
  for (let i = currentIdx - 1; i >= 0; i--) {
    if (isPlayable(sequence[i])) { prev = sequence[i]; break; }
  }

  let next: PlaylistContextItem | null = null;
  for (let i = currentIdx + 1; i < sequence.length; i++) {
    if (isPlayable(sequence[i])) { next = sequence[i]; break; }
  }

  return {
    playlist_id,
    playlist_name,
    total: sequence.length,
    current: sequence[currentIdx],
    previous: prev,
    next,
  };
}

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

type UpNextState =
  | { kind: "countdown"; target: PlaylistContextItem; remaining: number }
  | { kind: "end" }
  | null;

const PLAYLIST_AUTOPLAY_NEXT_KEY = "playlist_autoplay_next";
const PLAYLIST_AUTOPLAY_SECONDS = 3;

export function WatchPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const playlistIdParam = searchParams.get("playlist_id");
  const playlistId = playlistIdParam ? Number(playlistIdParam) : null;
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
  const [playlist, setPlaylist] = useState<PlaylistContext | null>(null);
  const [autoplayNext, setAutoplayNext] = useState(() => {
    if (typeof window === "undefined") return false;
    return window.localStorage.getItem(PLAYLIST_AUTOPLAY_NEXT_KEY) === "true";
  });
  const [upNextState, setUpNextState] = useState<UpNextState>(null);
  const upNextTickRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const upNextTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const upNextTargetRef = useRef<PlaylistContextItem | null>(null);

  // ── Autoplay & fullscreen state ───────────────────────────────────────────
  /** True when we should auto-start the new video on source load. */
  const [autoPlayOnLoad, setAutoPlayOnLoad] = useState(false);
  /** Ref set synchronously before navigate() so the new id-effect can pick it up. */
  const autoPlayScheduled = useRef(false);
  /** Whether the player container is in native fullscreen. */
  const [isFullscreen, setIsFullscreen] = useState(false);
  /** Ref: should we re-enter fullscreen when the new video loads? */
  const restoreFullscreenRef = useRef(false);
  /** Container div that we fullscreen (contains video + playlist overlay). */
  const playerContainerRef = useRef<HTMLDivElement>(null);

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
        if (playlistId !== null && Number.isFinite(playlistId)) {
          // Prefer the stored visual-sort sequence (set by PlaylistDetailPage).
          // Falls back to backend manual-position context for direct URL access.
          const storedNav = loadStoredNav(playlistId);
          const ctxFromNav = storedNav ? buildContextFromNav(storedNav, numericId) : null;
          if (ctxFromNav) {
            setPlaylist(ctxFromNav);
          } else {
            const ctx = await getPlaylistContext(playlistId, numericId);
            setPlaylist(ctx);
          }
        } else {
          setPlaylist(null);
        }
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
  }, [id, loadPlaybackData, playlistId]);

  useEffect(() => {
    try {
      window.localStorage.setItem(PLAYLIST_AUTOPLAY_NEXT_KEY, String(autoplayNext));
    } catch {
      // ignore storage failures
    }
  }, [autoplayNext]);

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

  const clearUpNextState = useCallback(() => {
    if (upNextTickRef.current) {
      clearInterval(upNextTickRef.current);
      upNextTickRef.current = null;
    }
    if (upNextTimeoutRef.current) {
      clearTimeout(upNextTimeoutRef.current);
      upNextTimeoutRef.current = null;
    }
    upNextTargetRef.current = null;
    setUpNextState(null);
  }, []);

  // When video id changes: pick up any scheduled autoplay intent
  useEffect(() => {
    if (autoPlayScheduled.current) {
      autoPlayScheduled.current = false;
      setAutoPlayOnLoad(true);
    } else {
      setAutoPlayOnLoad(false);
    }
  }, [id]);

  // Track native fullscreen changes
  useEffect(() => {
    const handler = () => {
      const isFull = !!(document.fullscreenElement && playerContainerRef.current?.contains(document.fullscreenElement));
      setIsFullscreen(isFull);

      // If user entered fullscreen on the <video> itself (not our container),
      // redirect to the container so our overlay is also in fullscreen.
      if (document.fullscreenElement && playerContainerRef.current &&
          document.fullscreenElement !== playerContainerRef.current &&
          playerContainerRef.current.contains(document.fullscreenElement)) {
        document.exitFullscreen()
          .then(() => playerContainerRef.current?.requestFullscreen())
          .catch(() => {});
      }
    };
    document.addEventListener("fullscreenchange", handler);
    return () => document.removeEventListener("fullscreenchange", handler);
  }, []);

  // Restore fullscreen after navigating to next video
  useEffect(() => {
    if (!restoreFullscreenRef.current) return;
    restoreFullscreenRef.current = false;
    if (!document.fullscreenElement && playerContainerRef.current) {
      playerContainerRef.current.requestFullscreen().catch(() => {});
    }
  }, [id]);

  useEffect(() => {
    clearUpNextState();
  }, [id, playlistId, clearUpNextState]);

  useEffect(() => {
    if (!autoplayNext) {
      clearUpNextState();
    }
  }, [autoplayNext, clearUpNextState]);

  useEffect(() => clearUpNextState, [clearUpNextState]);

  const qualityOptions = useMemo(() => {
    if (!playbackSource) return [];
    if (playbackSource.source_type === "hls") {
      return playerQualities.length > 0 ? playerQualities : playbackSource.available_qualities;
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

  // playlist IS the context returned directly from the backend (position-ordered, missing-skipped).
  // Alias it so existing JSX references remain readable.
  const playlistContext = playlist;

  const startUpNextCountdown = useCallback(
    (nextItem: PlaylistContextItem) => {
      if (!playlistContext) return;
      clearUpNextState();
      upNextTargetRef.current = nextItem;
      setUpNextState({ kind: "countdown", target: nextItem, remaining: PLAYLIST_AUTOPLAY_SECONDS });

      upNextTickRef.current = setInterval(() => {
        setUpNextState((prev) => {
          if (!prev || prev.kind !== "countdown") return prev;
          if (prev.remaining <= 1) return prev;
          return { ...prev, remaining: prev.remaining - 1 };
        });
      }, 1000);

      upNextTimeoutRef.current = setTimeout(() => {
        const target = upNextTargetRef.current;
        clearUpNextState();
        if (target) {
          autoPlayScheduled.current = true;
          restoreFullscreenRef.current = !!document.fullscreenElement;
          navigate(`/watch/${target.video_id}?playlist_id=${playlistContext.playlist_id}`);
        }
      }, PLAYLIST_AUTOPLAY_SECONDS * 1000);
    },
    [clearUpNextState, navigate, playlistContext]
  );

  const handleVideoEnded = useCallback(() => {
    if (!playlistContext || playlistContext.current === null) return;

    if (!autoplayNext) {
      if (!playlistContext.next) {
        setUpNextState({ kind: "end" });
      }
      return;
    }

    if (!playlistContext.next) {
      setUpNextState({ kind: "end" });
      return;
    }

    startUpNextCountdown(playlistContext.next);
  }, [autoplayNext, playlistContext, startUpNextCountdown]);

  const goPlaylistVideo = useCallback(
    (nextVideoId: number) => {
      if (!playlistContext) return;
      // Schedule autoplay and fullscreen restoration before navigating
      autoPlayScheduled.current = true;
      restoreFullscreenRef.current = !!document.fullscreenElement;
      navigate(`/watch/${nextVideoId}?playlist_id=${playlistContext.playlist_id}`);
    },
    [navigate, playlistContext]
  );

  const handlePlayUpNextNow = () => {
    if (upNextState?.kind !== "countdown") return;
    const target = upNextState.target;
    clearUpNextState();
    goPlaylistVideo(target.video_id);
  };

  const handleCancelUpNext = () => {
    clearUpNextState();
  };

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
    const ok = window.confirm(
      "Delete this video?\n\n" +
      "• The original media file will be permanently deleted from disk.\n" +
      "• Generated HLS cache and thumbnails will also be removed.\n" +
      "• Watch progress and related records will be removed.\n" +
      "• This action cannot be undone.\n\n" +
      "If deletion fails (read-only mount / permissions), nothing will be removed."
    );
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
      await prepareVideoHls(video.id, { force: false, qualities: ["480p"] });
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

  const handleTagsChanged = (tags: VideoTag[]) => {
    setVideo((prev) => {
      if (!prev) return prev;
      return { ...prev, tags };
    });
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
      {playlistContext ? (
        <section className="watch-playlist-strip watch-playlist-panel">
          <div className="watch-playlist-panel-main">
            <div>
              <strong>{playlistContext.playlist_name}</strong>
              <span className="watch-playlist-meta"> {playlistContext.current ? `${playlistContext.current.position} / ${playlistContext.total}` : `${playlistContext.total} item(s)`}</span>
            </div>
            <div className="watch-playlist-actions">
              <button className="btn-secondary" onClick={() => goPlaylistVideo(playlistContext.previous?.video_id ?? 0)} disabled={!playlistContext.previous}>
                Previous
              </button>
              <button className="btn-secondary" onClick={() => goPlaylistVideo(playlistContext.next?.video_id ?? 0)} disabled={!playlistContext.next}>
                Next
              </button>
              {playlistContext.next ? (
                <label className="watch-playlist-autoplay-toggle">
                  <input type="checkbox" checked={autoplayNext} onChange={(event) => setAutoplayNext(event.target.checked)} />
                  <span>Autoplay next</span>
                </label>
              ) : null}
            </div>
          </div>

          {playlistContext.current ? (
            <div className="watch-playlist-up-next-preview">
              {playlistContext.next ? (
                <>
                  <div className="watch-playlist-up-next-thumb">
                    {playlistContext.next.thumbnail_url ? (
                      <img src={playlistContext.next.thumbnail_url} alt={playlistContext.next.display_title} loading="lazy" decoding="async" />
                    ) : (
                      <div className="thumb placeholder">No Thumbnail</div>
                    )}
                  </div>
                  <div className="watch-playlist-up-next-copy">
                    <span className="watch-playlist-up-next-label">Up next</span>
                    <strong>{playlistContext.next.display_title}</strong>
                  </div>
                </>
              ) : (
                <span className="watch-playlist-end">End of playlist</span>
              )}
            </div>
          ) : (
            <div className="watch-playlist-warning">This video is no longer in the playlist.</div>
          )}
        </section>
      ) : null}

      {upNextState?.kind === "countdown" ? (
        <div className="watch-up-next-overlay">
          <div className="watch-up-next-card">
            <div className="watch-up-next-heading">Up next</div>
            <strong className="watch-up-next-title">{upNextState.target.display_title}</strong>
            <div className="watch-up-next-countdown">Playing in {upNextState.remaining} second{upNextState.remaining === 1 ? "" : "s"}</div>
            <div className="watch-up-next-actions">
              <button className="btn-primary" onClick={handlePlayUpNextNow}>Play now</button>
              <button className="btn-secondary" onClick={handleCancelUpNext}>Cancel</button>
            </div>
          </div>
        </div>
      ) : null}

      {upNextState?.kind === "end" ? <div className="notice watch-playlist-end-notice">End of playlist</div> : null}
      <VideoTagsPanel videoId={video.id} onTagsChanged={handleTagsChanged} />

      {askResume && progress && (
        <div className="resume-banner">
          <span>Continue from {formatDuration(progress.position_seconds)}?</span>
          <button className="btn-primary" onClick={handleResume}>Resume</button>
          <button className="btn-secondary" onClick={handleFromBeginning}>Start from beginning</button>
        </div>
      )}

      <div
        ref={playerContainerRef}
        className={`player-container${isFullscreen ? " player-container--fullscreen" : ""}`}
      >
        <VideoPlayer
          video={video}
          sourceType={playbackSource?.source_type ?? "none"}
          streamUrl={playbackSource?.stream_url ?? null}
          selectedQuality={selectedQuality}
          onAvailableQualities={setPlayerQualities}
          initialPosition={initialPosition}
          onEnded={handleVideoEnded}
          autoPlay={autoPlayOnLoad}
          onPlay={() => setAutoPlayOnLoad(false)}
        />

        {/* Playlist controls overlay — shown on hover and in fullscreen */}
        {playlistContext ? (
          <div className="player-playlist-overlay">
            <button
              className="player-overlay-btn"
              onClick={() => goPlaylistVideo(playlistContext.previous?.video_id ?? 0)}
              disabled={!playlistContext.previous}
              title={playlistContext.previous ? `Previous: ${playlistContext.previous.display_title}` : "No previous video"}
            >
              ⏮
            </button>
            <button
              className="player-overlay-btn player-overlay-btn--stop"
              onClick={() => {
                clearUpNextState();
                if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
              }}
              title="Stop / Exit fullscreen"
            >
              ⏹
            </button>
            <button
              className="player-overlay-btn"
              onClick={() => goPlaylistVideo(playlistContext.next?.video_id ?? 0)}
              disabled={!playlistContext.next}
              title={playlistContext.next ? `Next: ${playlistContext.next.display_title}` : "End of playlist"}
            >
              ⏭
            </button>
          </div>
        ) : null}

        {/* Custom fullscreen toggle */}
        <button
          className="player-fullscreen-btn"
          title={isFullscreen ? "Exit fullscreen" : "Fullscreen"}
          onClick={() => {
            if (document.fullscreenElement) {
              document.exitFullscreen().catch(() => {});
            } else {
              playerContainerRef.current?.requestFullscreen().catch(() => {});
            }
          }}
        >
          {isFullscreen ? "⤡" : "⤢"}
        </button>
      </div>

      {video.media_status === "probe_failed_possible_video" && (
        <div className="notice">
          Could not read metadata. This may be an unsupported or damaged media file.
        </div>
      )}

      <div className="watch-details-grid">
        <section className="watch-details-card">
          <h3>File</h3>
          <p><strong>Display title:</strong> {video.title}</p>
          <p><strong>Filename:</strong> {video.filename}</p>
          <p><strong>Relative path:</strong> {video.relative_path}</p>
          <p><strong>Extension:</strong> {video.extension.toUpperCase()}</p>
          <p><strong>File size:</strong> {formatSize(video.size)}</p>
          {video.file_modified_at ? <p><strong>Modified:</strong> {new Date(video.file_modified_at).toLocaleString()}</p> : null}
          <p><strong>Indexed:</strong> {new Date(video.indexed_at).toLocaleString()}</p>
        </section>

        <section className="watch-details-card">
          <h3>Library</h3>
          <p><strong>Media source:</strong> {video.library_root_name ?? "Unknown"}</p>
          <p><strong>Media source ID:</strong> {video.library_root_id ?? "—"}</p>
          {video.folder_path ? <p><strong>Folder within source:</strong> {video.folder_path}</p> : null}
        </section>

        <section className="watch-details-card">
          <h3>Playback / HLS</h3>
          <p><strong>Current source:</strong> {playbackSource?.source_type ?? "loading"}</p>
          <p><strong>Source reason:</strong> {playbackSource?.reason ?? "Loading..."}</p>
          <p>
            <strong>HLS status:</strong> {hlsStatus?.status ?? "idle"}
            {hlsStatus?.current_quality ? ` (${hlsStatus.current_quality})` : ""}
            {hlsStatus?.progress_percent !== null && hlsStatus?.progress_percent !== undefined
              ? ` - ${Math.round(hlsStatus.progress_percent)}%`
              : ""}
          </p>
          {hlsStatus?.error_message ? <p className="card-warning">{hlsStatus.error_message}</p> : null}
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
            {hlsStatus?.status === "completed" && playbackSource?.source_type !== "hls" ? (
              <button className="btn-secondary" onClick={handleUseHls}>Use HLS</button>
            ) : null}
            {playbackSource?.source_type === "hls" ? <span className="diagnostics-hint">HLS ready</span> : null}
          </div>
        </section>

        <section className="watch-details-card">
          <h3>Media / Codecs</h3>
          <p><strong>Duration:</strong> {formatDuration(video.duration)}</p>
          <p><strong>Resolution:</strong> {video.width && video.height ? `${video.width}×${video.height}` : "Unknown"}</p>
          <p><strong>Container format:</strong> {video.container_format ?? "Unknown"}</p>
          <p><strong>Video codec:</strong> {video.video_codec ?? "Unknown"}</p>
          <p><strong>Audio codec:</strong> {video.audio_codec ?? "Unknown"}</p>
          <p><strong>Pixel format:</strong> {video.pixel_format ?? "Unknown"}</p>
          <p><strong>Audio channels:</strong> {video.audio_channels ?? "Unknown"}</p>
          <p><strong>Sample rate:</strong> {video.audio_sample_rate ?? "Unknown"}</p>
        </section>

        <section className="watch-details-card">
          <h3>Compatibility</h3>
          <p><strong>Compatibility:</strong> {video.compatibility_status ?? "Unknown"}</p>
          <p><strong>Effective status:</strong> {video.effective_compatibility_status ?? "Unknown"}</p>
          <p><strong>Compatibility source:</strong> {video.compatibility_source ?? "unknown"}</p>
          <p><strong>Media profile key:</strong> {video.media_profile_key ?? "Unknown"}</p>
          <p><strong>Manual profile status:</strong> {video.manual_playback_status ?? "not set"}</p>
          {video.compatibility_reason ? <p><strong>Reason:</strong> {video.compatibility_reason}</p> : null}
          {video.probe_error ? <p><strong>Probe error:</strong> {video.probe_error}</p> : null}
          {video.thumbnail_error ? <p><strong>Thumbnail error:</strong> {video.thumbnail_error}</p> : null}
        </section>
      </div>
    </div>
  );
}
