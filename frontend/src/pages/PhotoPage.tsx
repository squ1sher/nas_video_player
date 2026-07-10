import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { fetchPhoto, getPhotoOriginalUrl } from "../api/client";
import type { PhotoDetail } from "../types/video";

function formatBytes(bytes: number): string {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function formatDate(value: string | null): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

export function PhotoPage() {
  const { id } = useParams<{ id: string }>();
  const [photo, setPhoto] = useState<PhotoDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    const run = async () => {
      if (!id) return;
      try {
        setLoading(true);
        setError(null);
        const payload = await fetchPhoto(id);
        if (mounted) setPhoto(payload);
      } catch (err) {
        if (mounted) setError(err instanceof Error ? err.message : "Failed to load photo");
      } finally {
        if (mounted) setLoading(false);
      }
    };
    void run();
    return () => {
      mounted = false;
    };
  }, [id]);

  if (loading) return <div className="status">Loading photo...</div>;
  if (error) return <div className="error">{error}</div>;
  if (!photo) return <div className="status">Photo not found.</div>;

  const previewSrc = photo.preview_url || `/api/photos/${photo.id}/preview`;

  return (
    <div className="page page-watch">
      <div style={{ marginBottom: 12 }}>
        <Link to="/" className="btn-secondary">Back to library</Link>
      </div>
      <div className="video-player-shell" style={{ padding: 12 }}>
        <div style={{ display: "flex", justifyContent: "center", width: "100%", position: "relative" }}>
          {photo.raw_format ? (
            <span
              style={{
                position: "absolute",
                top: 8,
                left: 8,
                background: "rgba(0,0,0,0.7)",
                color: "#fff",
                fontSize: 12,
                fontWeight: 700,
                padding: "3px 8px",
                borderRadius: 4,
                letterSpacing: 0.5,
                zIndex: 1,
              }}
            >
              RAW
            </span>
          ) : null}
          <img
            src={previewSrc}
            alt={photo.filename}
            style={{ maxWidth: "100%", maxHeight: "70vh", objectFit: "contain", borderRadius: 8 }}
            onError={(e) => {
              // Fall back to the thumbnail endpoint if preview failed to load.
              const fallback = `/api/photos/${photo.id}/thumbnail`;
              if (e.currentTarget.src.indexOf("/thumbnail") === -1) {
                e.currentTarget.src = fallback;
              }
            }}
          />
        </div>

        <div className="video-meta" style={{ marginTop: 16 }}>
          <h2>{photo.filename}</h2>
          <div className="meta-grid">
            <div><strong>Captured:</strong> {formatDate(photo.captured_at)}</div>
            <div><strong>Date Source:</strong> {photo.date_source || "-"}</div>
            <div><strong>Dimensions:</strong> {photo.width && photo.height ? `${photo.width} x ${photo.height}` : "-"}</div>
            <div><strong>Size:</strong> {formatBytes(photo.file_size)}</div>
            <div><strong>Camera:</strong> {[photo.camera_make, photo.camera_model].filter(Boolean).join(" ") || "-"}</div>
            <div><strong>Extension:</strong> {photo.extension}</div>
            <div><strong>Source:</strong> {photo.media_source_name || "Unassigned"}</div>
            <div><strong>RAW:</strong> {photo.raw_format ? "Yes" : "No"}</div>
          </div>
          <div style={{ marginTop: 12 }}>
            <a className="btn-primary" href={getPhotoOriginalUrl(photo.id)}>
              Download original
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}

