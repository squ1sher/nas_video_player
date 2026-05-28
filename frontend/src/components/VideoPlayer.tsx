import { useEffect, useRef, useState } from "react";
import Hls from "hls.js";

import { updateProgress } from "../api/client";
import { CompatibilityBadge } from "./CompatibilityBadge";
import type { VideoDetail } from "../types/video";

type Props = {
  video: VideoDetail;
  sourceType: "hls" | "original" | "none";
  streamUrl: string | null;
  selectedQuality: string;
  onAvailableQualities?: (qualities: string[]) => void;
  initialPosition?: number;
  onError?: () => void;
  onEnded?: () => void;
};

export function VideoPlayer({
  video,
  sourceType,
  streamUrl,
  selectedQuality,
  onAvailableQualities,
  initialPosition = 0,
  onError,
  onEnded,
}: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const hlsRef = useRef<Hls | null>(null);
  const [playerError, setPlayerError] = useState(false);

  const applyHlsQuality = (hls: Hls, quality: string) => {
    if (quality === "auto") {
      hls.currentLevel = -1;
      return;
    }
    const qualityHeight = Number(quality.replace("p", ""));
    const idx = hls.levels.findIndex((level) => level.height === qualityHeight);
    if (idx >= 0) hls.currentLevel = idx;
  };

  const saveProgress = (el: HTMLVideoElement, keepalive = false): Promise<void> => {
    if (!el.duration || el.duration === Infinity || el.currentTime === 0) return Promise.resolve();
    return updateProgress(video.id, el.currentTime, el.duration, keepalive)
      .then(() => undefined)
      .catch(() => undefined);
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

    setPlayerError(false);

    if (hlsRef.current) {
      hlsRef.current.destroy();
      hlsRef.current = null;
    }

    if (!streamUrl || sourceType === "none") {
      el.removeAttribute("src");
      el.load();
      return;
    }

    if (sourceType === "hls") {
      if (el.canPlayType("application/vnd.apple.mpegurl")) {
        el.src = streamUrl;
      } else if (Hls.isSupported()) {
        const hls = new Hls({
          enableWorker: true,
        });
        hlsRef.current = hls;
        hls.loadSource(streamUrl);
        hls.attachMedia(el);
        hls.on(Hls.Events.MANIFEST_PARSED, () => {
          const mapped = Array.from(new Set(hls.levels.map((level) => `${level.height}p`)))
            .sort((a, b) => Number(a.replace("p", "")) - Number(b.replace("p", "")));
          onAvailableQualities?.(["auto", ...mapped]);
          applyHlsQuality(hls, selectedQuality);
        });
        hls.on(Hls.Events.ERROR, (_event, data) => {
          if (data.fatal) {
            setPlayerError(true);
            onError?.();
          }
        });
      } else {
        setPlayerError(true);
        onError?.();
      }
    } else {
      el.src = streamUrl;
      onAvailableQualities?.(["original"]);
    }

    return () => {
      if (hlsRef.current) {
        hlsRef.current.destroy();
        hlsRef.current = null;
      }
    };
  }, [sourceType, streamUrl, onAvailableQualities, onError, selectedQuality]);

  useEffect(() => {
    const hls = hlsRef.current;
    if (!hls || sourceType !== "hls") return;
    applyHlsQuality(hls, selectedQuality);
  }, [selectedQuality, sourceType]);

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
    const onVideoEnded = () => {
      stopSaveInterval();
      void saveProgress(el).finally(() => {
        onEnded?.();
      });
    };

    const onBeforeUnload = () => {
      saveProgress(el, true); // keepalive=true for page close
    };

    el.addEventListener("loadedmetadata", onLoadedMetadata);
    el.addEventListener("play", onPlay);
    el.addEventListener("pause", onPause);
    el.addEventListener("ended", onVideoEnded);
    window.addEventListener("beforeunload", onBeforeUnload);

    return () => {
      el.removeEventListener("loadedmetadata", onLoadedMetadata);
      el.removeEventListener("play", onPlay);
      el.removeEventListener("pause", onPause);
      el.removeEventListener("ended", onVideoEnded);
      window.removeEventListener("beforeunload", onBeforeUnload);
      stopSaveInterval();
    };
  }, [video.id, initialPosition, onEnded]);

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
      preload="auto"
      onError={() => {
        setPlayerError(true);
        onError?.();
      }}
    />
  );
}
