import { useEffect, useRef, useState } from "react";
import { updateProgress } from "../api/client";
import { CompatibilityBadge } from "./CompatibilityBadge";
import type { VideoDetail } from "../types/video";

type Props = {
  video: VideoDetail;
  initialPosition?: number;
  onError?: () => void;
};

export function VideoPlayer({ video, initialPosition = 0, onError }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [playerError, setPlayerError] = useState(false);

  const saveProgress = (el: HTMLVideoElement, keepalive = false) => {
    if (!el.duration || el.duration === Infinity || el.currentTime === 0) return;
    void updateProgress(video.id, el.currentTime, el.duration, keepalive).catch(() => {
      // Silently ignore progress save failures
    });
  };

  const startSaveInterval = (el: HTMLVideoElement) => {
    if (intervalRef.current) clearInterval(intervalRef.current);
    intervalRef.current = setInterval(() => {
      if (!el.paused && !el.ended) saveProgress(el);
    }, 5000);
  };

  const stopSaveInterval = () => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  };

  useEffect(() => {
    const el = videoRef.current;
    if (!el) return;

    const onLoadedMetadata = () => {
      if (initialPosition > 0 && el.duration && initialPosition < el.duration) {
        el.currentTime = initialPosition;
      }
    };

    const onPlay = () => startSaveInterval(el);
    const onPause = () => {
      stopSaveInterval();
      saveProgress(el);
    };
    const onEnded = () => {
      stopSaveInterval();
      saveProgress(el);
    };

    const onBeforeUnload = () => {
      saveProgress(el, true); // keepalive=true for page close
    };

    el.addEventListener("loadedmetadata", onLoadedMetadata);
    el.addEventListener("play", onPlay);
    el.addEventListener("pause", onPause);
    el.addEventListener("ended", onEnded);
    window.addEventListener("beforeunload", onBeforeUnload);

    return () => {
      el.removeEventListener("loadedmetadata", onLoadedMetadata);
      el.removeEventListener("play", onPlay);
      el.removeEventListener("pause", onPause);
      el.removeEventListener("ended", onEnded);
      window.removeEventListener("beforeunload", onBeforeUnload);
      stopSaveInterval();
    };
  }, [video.id, initialPosition]);

  if (playerError) {
    return (
      <div className="player-error">
        <p className="player-error-msg">
          &#9888; This file may not be supported by your browser.
        </p>
        <div className="player-error-details">
          <p>
            <strong>Container:</strong> {video.extension.toUpperCase()}
          </p>
          <p>
            <strong>Video codec:</strong> {video.video_codec || "Unknown"}
          </p>
          <p>
            <strong>Audio codec:</strong> {video.audio_codec || "Unknown"}
          </p>
          {video.compatibility_status && (
            <p>
              <strong>Compatibility:</strong>{" "}
              <CompatibilityBadge
                status={video.compatibility_status}
                reason={video.compatibility_reason}
              />
            </p>
          )}
          {video.compatibility_reason && (
            <p className="compat-reason">{video.compatibility_reason}</p>
          )}
        </div>
      </div>
    );
  }

  return (
    <video
      ref={videoRef}
      className="video-player"
      controls
      preload="metadata"
      src={`/api/videos/${video.id}/stream`}
      onError={() => {
        setPlayerError(true);
        onError?.();
      }}
    />
  );
}
