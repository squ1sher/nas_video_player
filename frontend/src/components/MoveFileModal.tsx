import { useEffect, useState } from "react";

import { browseMediaSources, createMediaFolder, MoveConflictError } from "../api/client";
import type { MoveConflictResolution } from "../api/client";
import type { MediaSourceBrowseItem } from "../types/video";

type MoveFileModalProps = {
  open: boolean;
  filename: string;
  currentDisplayPath: string;
  onClose: () => void;
  onConfirm: (targetDirectory: string, onConflict: MoveConflictResolution) => Promise<void>;
};

/**
 * Modal for relocating a video/photo's source file. Lets the user type a
 * destination path directly, or browse the media library visually (reusing
 * the same directory browser used by Settings → Media Sources), including
 * creating a brand-new subfolder. If the destination already has a file with
 * the same name, the user is asked whether to overwrite it or keep both
 * (the moved file gets an incrementing " (n)" suffix).
 */
export function MoveFileModal({ open, filename, currentDisplayPath, onClose, onConfirm }: MoveFileModalProps) {
  const [targetPath, setTargetPath] = useState("");
  const [browseOpen, setBrowseOpen] = useState(false);
  const [browsePath, setBrowsePath] = useState("");
  const [browseItems, setBrowseItems] = useState<MediaSourceBrowseItem[]>([]);
  const [browseLoading, setBrowseLoading] = useState(false);
  const [browseError, setBrowseError] = useState<string | null>(null);
  const [creatingFolder, setCreatingFolder] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");
  const [folderBusy, setFolderBusy] = useState(false);
  const [moving, setMoving] = useState(false);
  const [moveError, setMoveError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<{ message: string; suggestedName: string } | null>(null);

  useEffect(() => {
    if (open) {
      const currentDir = currentDisplayPath.split("/").slice(0, -1).join("/") || "/volume1";
      setTargetPath(currentDir);
      setMoveError(null);
      setConflict(null);
      setBrowseOpen(false);
      setCreatingFolder(false);
      setNewFolderName("");
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

  const handleCreateFolder = async () => {
    const name = newFolderName.trim();
    if (!name) return;
    setFolderBusy(true);
    setBrowseError(null);
    try {
      const parentDisplay = browsePath ? `/volume1/${browsePath}` : "/volume1";
      const created = await createMediaFolder(parentDisplay, name);
      setNewFolderName("");
      setCreatingFolder(false);
      await loadBrowse(browsePath);
      // Jump straight into the newly created folder for convenience.
      setBrowsePath(created.relative_path);
      await loadBrowse(created.relative_path);
    } catch (e) {
      setBrowseError(e instanceof Error ? e.message : String(e));
    } finally {
      setFolderBusy(false);
    }
  };

  const attemptMove = async (onConflict: MoveConflictResolution) => {
    setMoving(true);
    setMoveError(null);
    try {
      await onConfirm(targetPath.trim(), onConflict);
      onClose();
    } catch (e) {
      if (e instanceof MoveConflictError) {
        setConflict({ message: e.message, suggestedName: e.suggestedName });
        return;
      }
      setMoveError(e instanceof Error ? e.message : String(e));
    } finally {
      setMoving(false);
    }
  };

  const handleMove = async () => {
    if (!targetPath.trim()) {
      setMoveError("Please enter or select a destination folder.");
      return;
    }
    setConflict(null);
    await attemptMove("fail");
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

          {conflict && (
            <div className="notice" style={{ marginTop: 8 }}>
              <p style={{ marginTop: 0 }}>{conflict.message}</p>
              <div style={{ display: "flex", gap: 8 }}>
                <button className="btn-secondary" onClick={() => void attemptMove("overwrite")} disabled={moving}>
                  Overwrite
                </button>
                <button className="btn-secondary" onClick={() => void attemptMove("keep_both")} disabled={moving}>
                  Keep both{conflict.suggestedName ? ` (as "${conflict.suggestedName}")` : ""}
                </button>
                <button className="btn-secondary" onClick={() => setConflict(null)} disabled={moving}>
                  Cancel
                </button>
              </div>
            </div>
          )}

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

              <div style={{ display: "flex", gap: 8, margin: "6px 0", flexWrap: "wrap" }}>
                {browsePath && <button className="btn-sm browse-up-btn" onClick={() => void handleBrowseUp()}>↑ Up</button>}
                <button className="btn-sm" onClick={handleUseCurrentFolder}>Use this folder</button>
                <button className="btn-sm" onClick={() => setCreatingFolder((v) => !v)}>+ New folder</button>
              </div>

              {creatingFolder && (
                <div style={{ display: "flex", gap: 8, margin: "6px 0" }}>
                  <input
                    type="text"
                    value={newFolderName}
                    onChange={(e) => setNewFolderName(e.target.value)}
                    placeholder="New folder name"
                    style={{ flex: 1 }}
                    disabled={folderBusy}
                  />
                  <button className="btn-sm" onClick={() => void handleCreateFolder()} disabled={folderBusy || !newFolderName.trim()}>
                    {folderBusy ? "Creating..." : "Create"}
                  </button>
                </div>
              )}

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
          <button className="btn-primary" onClick={() => void handleMove()} disabled={moving || !!conflict}>
            {moving ? "Moving..." : "Move file"}
          </button>
        </div>
      </div>
    </div>
  );
}

