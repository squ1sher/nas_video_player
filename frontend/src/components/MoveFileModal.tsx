import { useEffect, useState } from "react";

import { browseMediaSources } from "../api/client";
import type { MediaSourceBrowseItem } from "../types/video";

type MoveFileModalProps = {
  open: boolean;
  filename: string;
  currentDisplayPath: string;
  onClose: () => void;
  onConfirm: (targetDirectory: string) => Promise<void>;
};

/**
 * Modal for relocating a video/photo's source file. Lets the user type a
 * destination path directly, or browse the media library visually (reusing
 * the same directory browser used by Settings → Media Sources).
 */
export function MoveFileModal({ open, filename, currentDisplayPath, onClose, onConfirm }: MoveFileModalProps) {
  const [targetPath, setTargetPath] = useState("");
  const [browseOpen, setBrowseOpen] = useState(false);
  const [browsePath, setBrowsePath] = useState("");
  const [browseItems, setBrowseItems] = useState<MediaSourceBrowseItem[]>([]);
  const [browseLoading, setBrowseLoading] = useState(false);
  const [browseError, setBrowseError] = useState<string | null>(null);
  const [moving, setMoving] = useState(false);
  const [moveError, setMoveError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      const currentDir = currentDisplayPath.split("/").slice(0, -1).join("/") || "/volume1";
      setTargetPath(currentDir);
      setMoveError(null);
      setBrowseOpen(false);
    }
  }, [open, currentDisplayPath]);

  if (!open) return null;

  const loadBrowse = async (rel: string) => {
    setBrowseLoading(true);
    setBrowseError(null);
    try {
      const items = await browseMediaSources(rel);
      setBrowseItems(items);
    } catch (e) {
      setBrowseError(e instanceof Error ? e.message : String(e));
      setBrowseItems([]);
    } finally {
      setBrowseLoading(false);
    }
  };

  const openBrowse = async () => {
    setBrowseOpen(true);
    setBrowsePath("");
    await loadBrowse("");
  };

  const handleBrowseNavigate = async (item: MediaSourceBrowseItem) => {
    if (item.blocked) return;
    setBrowsePath(item.relative_path);
    await loadBrowse(item.relative_path);
  };

  const handleBrowseUp = async () => {
    const parts = browsePath.split("/").filter(Boolean);
    parts.pop();
    const newPath = parts.join("/");
    setBrowsePath(newPath);
    await loadBrowse(newPath);
  };

  const handleUseCurrentFolder = () => {
    setTargetPath(browsePath ? `/volume1/${browsePath}` : "/volume1");
    setBrowseOpen(false);
  };

  const handleBrowseSelect = (item: MediaSourceBrowseItem) => {
    setTargetPath(item.display_path);
    setBrowseOpen(false);
  };

  const handleMove = async () => {
    if (!targetPath.trim()) {
      setMoveError("Please enter or select a destination folder.");
      return;
    }
    setMoving(true);
    setMoveError(null);
    try {
      await onConfirm(targetPath.trim());
      onClose();
    } catch (e) {
      setMoveError(e instanceof Error ? e.message : String(e));
    } finally {
      setMoving(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Move file</h3>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          <p style={{ marginTop: 0 }}>
            Moving <strong>{filename}</strong> to a new folder. Generated previews/HLS streams keep
            working automatically; the file itself is relocated on disk.
          </p>
          <label style={{ display: "block", marginBottom: 8 }}>
            Destination folder
            <input
              type="text"
              value={targetPath}
              onChange={(e) => setTargetPath(e.target.value)}
              placeholder="/volume1/sclad/Movies"
              style={{ width: "100%", marginTop: 4 }}
            />
          </label>
          <button className="btn-secondary" onClick={() => void openBrowse()} style={{ marginBottom: 8 }}>
            Browse folders...
          </button>

          {moveError && <div className="error" style={{ marginTop: 8 }}>{moveError}</div>}

          {browseOpen && (
            <div style={{ border: "1px solid var(--border-color, #444)", borderRadius: 6, padding: 8, marginTop: 8 }}>
              <div className="browse-breadcrumb">
                <span className="browse-breadcrumb-item browse-breadcrumb-link" onClick={() => void loadBrowse("").then(() => setBrowsePath(""))}>
                  /volume1
                </span>
                {browsePath.split("/").filter(Boolean).map((part, i, arr) => {
                  const partial = arr.slice(0, i + 1).join("/");
                  return (
                    <span key={partial}>
                      {" / "}
                      <span
                        className="browse-breadcrumb-item browse-breadcrumb-link"
                        onClick={() => void loadBrowse(partial).then(() => setBrowsePath(partial))}
                      >
                        {part}
                      </span>
                    </span>
                  );
                })}
              </div>

              <div style={{ display: "flex", gap: 8, margin: "6px 0" }}>
                {browsePath && <button className="btn-sm browse-up-btn" onClick={() => void handleBrowseUp()}>↑ Up</button>}
                <button className="btn-sm" onClick={handleUseCurrentFolder}>Use this folder</button>
              </div>

              {browseLoading && <div className="settings-loading">Loading...</div>}
              {browseError && <div className="settings-error">{browseError}</div>}
              {!browseLoading && !browseError && browseItems.length === 0 && (
                <div className="settings-empty">No subfolders found.</div>
              )}

              {!browseLoading && browseItems.length > 0 && (
                <ul className="browse-list">
                  {browseItems.map((item) => (
                    <li key={item.relative_path} className={`browse-item${item.blocked ? " browse-item-blocked" : ""}`}>
                      <span
                        className="browse-item-name"
                        onClick={() => !item.blocked && void handleBrowseNavigate(item)}
                        title={item.blocked ? "Blocked" : item.display_path}
                      >
                        📁 {item.name}
                        {item.blocked && <span className="browse-blocked-label"> (blocked)</span>}
                      </span>
                      {!item.blocked && (
                        <button className="btn-sm" onClick={() => handleBrowseSelect(item)}>Select</button>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
        <div className="modal-footer">
          <button className="btn-secondary" onClick={onClose} disabled={moving}>Cancel</button>
          <button className="btn-primary" onClick={() => void handleMove()} disabled={moving}>
            {moving ? "Moving..." : "Move file"}
          </button>
        </div>
      </div>
    </div>
  );
}
