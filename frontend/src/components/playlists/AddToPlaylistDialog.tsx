import { useEffect, useState } from "react";

import { addPlaylistItems, createPlaylist } from "../../api/client";
import type { PlaylistSummary } from "../../types/video";

type Props = {
  open: boolean;
  selectedCount: number;
  selectedVideoIds: number[];
  playlists: PlaylistSummary[];
  onClose: () => void;
  onDone: (message: string) => void;
};

export function AddToPlaylistDialog({
  open,
  selectedCount,
  selectedVideoIds,
  playlists,
  onClose,
  onDone,
}: Props) {
  const [mode, setMode] = useState<"existing" | "new">("existing");
  const [selectedPlaylistId, setSelectedPlaylistId] = useState<number | null>(null);
  const [newName, setNewName] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    if (playlists.length > 0) {
      setSelectedPlaylistId(playlists[0].id);
      setMode("existing");
    } else {
      setSelectedPlaylistId(null);
      setMode("new");
    }
    setNewName("");
    setNewDescription("");
    setBusy(false);
    setError(null);
  }, [open, playlists]);

  if (!open) return null;

  const canSubmit =
    selectedCount > 0 &&
    !busy &&
    ((mode === "existing" && selectedPlaylistId !== null) || (mode === "new" && newName.trim().length > 0));

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    try {
      let playlistId = selectedPlaylistId;
      if (mode === "new") {
        const created = await createPlaylist({
          name: newName.trim(),
          description: newDescription.trim() || null,
        });
        playlistId = created.id;
      }
      if (!playlistId) {
        setError("Select playlist first.");
        setBusy(false);
        return;
      }

      const result = await addPlaylistItems(playlistId, selectedVideoIds);
      const message = `Added ${result.added.length} video(s). ${result.skipped_existing.length} already existed in playlist.`;
      onDone(message);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add videos to playlist.");
      setBusy(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={busy ? undefined : onClose}>
      <div className="modal-box" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <h3>Add selected videos to playlist</h3>
          <button className="modal-close" onClick={onClose} disabled={busy}>x</button>
        </div>
        <div className="modal-body">
          <p>{selectedCount} video(s) selected</p>

          {playlists.length > 0 ? (
            <label className="playlist-field">
              <input
                type="radio"
                checked={mode === "existing"}
                onChange={() => setMode("existing")}
                disabled={busy}
              />
              <span>Use existing playlist</span>
            </label>
          ) : null}

          {mode === "existing" ? (
            <select
              value={selectedPlaylistId ?? ""}
              onChange={(event) => setSelectedPlaylistId(Number(event.target.value))}
              disabled={busy || playlists.length === 0}
            >
              {playlists.map((playlist) => (
                <option key={playlist.id} value={playlist.id}>
                  {playlist.name} ({playlist.item_count})
                </option>
              ))}
            </select>
          ) : null}

          <label className="playlist-field">
            <input
              type="radio"
              checked={mode === "new"}
              onChange={() => setMode("new")}
              disabled={busy}
            />
            <span>Create new playlist</span>
          </label>

          {mode === "new" ? (
            <div className="playlist-new-form">
              <input
                placeholder="Playlist name"
                value={newName}
                onChange={(event) => setNewName(event.target.value)}
                disabled={busy}
              />
              <textarea
                placeholder="Description (optional)"
                value={newDescription}
                onChange={(event) => setNewDescription(event.target.value)}
                disabled={busy}
                rows={3}
              />
            </div>
          ) : null}

          {error ? <div className="settings-error">{error}</div> : null}
        </div>
        <div className="modal-footer">
          <button className="btn-secondary" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="btn-primary" onClick={() => void handleSubmit()} disabled={!canSubmit}>
            {busy ? "Adding..." : "Add"}
          </button>
        </div>
      </div>
    </div>
  );
}


