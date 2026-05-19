import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  browseMediaSources,
  createMediaSource,
  deleteMediaSource,
  getMediaSources,
  scanMediaSource,
  updateMediaSource,
  validateMediaSourcePath,
} from "../api/client";
import type { LibraryRoot, LibraryRootIn, MediaSourceBrowseItem, PathValidationResult } from "../types/video";

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });
  } catch { return iso; }
}

function StatusBadge({ status }: { status: string | null }) {
  if (!status) return <span className="badge badge-unknown">—</span>;
  const cls =
    status === "completed" || status === "completed_with_errors" ? "badge-ok" :
    status === "error" ? "badge-err" :
    status === "cancelled" ? "badge-warn" : "badge-unknown";
  return <span className={`badge ${cls}`}>{status}</span>;
}

type ModalState = { mode: "add" | "edit"; source?: LibraryRoot };

const DEFAULT_FORM: LibraryRootIn = {
  name: "",
  path: "",
  media_type: "video",
  enabled: true,
  recursive: true,
  scan_priority: 100,
};

export function SettingsPage() {
  const navigate = useNavigate();
  const [sources, setSources] = useState<LibraryRoot[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modal, setModal] = useState<ModalState | null>(null);
  const [form, setForm] = useState<LibraryRootIn>(DEFAULT_FORM);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [validating, setValidating] = useState(false);
  const [validation, setValidation] = useState<PathValidationResult | null>(null);
  const [scanning, setScanning] = useState<number | null>(null);
  const [scanMsg, setScanMsg] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<LibraryRoot | null>(null);

  // Browse state
  const [browseOpen, setBrowseOpen] = useState(false);
  const [browsePath, setBrowsePath] = useState("");   // current browse relative path
  const [browseItems, setBrowseItems] = useState<MediaSourceBrowseItem[]>([]);
  const [browseLoading, setBrowseLoading] = useState(false);
  const [browseError, setBrowseError] = useState<string | null>(null);

  const pathRef = useRef<HTMLInputElement>(null);

  const load = async () => {
    try {
      const data = await getMediaSources();
      setSources(data);
      setError(null);
    } catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  };

  useEffect(() => { void load(); }, []);

  // ── Browse helpers ──────────────────────────────────────────────────────

  const openBrowse = async (startPath = "") => {
    setBrowseOpen(true);
    setBrowsePath(startPath);
    setBrowseError(null);
    await loadBrowse(startPath);
  };

  const loadBrowse = async (rel: string) => {
    setBrowseLoading(true);
    setBrowseError(null);
    try {
      const items = await browseMediaSources(rel);
      setBrowseItems(items);
    } catch (e) {
      setBrowseError(String(e));
      setBrowseItems([]);
    } finally {
      setBrowseLoading(false);
    }
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

  const handleBrowseSelect = (item: MediaSourceBrowseItem) => {
    setForm((f) => ({ ...f, path: item.internal_path }));
    setValidation(null);
    setBrowseOpen(false);
  };

  // ── Modal helpers ───────────────────────────────────────────────────────

  const openAdd = () => {
    setForm(DEFAULT_FORM);
    setValidation(null);
    setSaveError(null);
    setModal({ mode: "add" });
  };

  const openEdit = (source: LibraryRoot) => {
    setForm({
      name: source.name,
      path: source.path,
      media_type: source.media_type,
      enabled: source.enabled,
      recursive: source.recursive,
      scan_priority: source.scan_priority,
    });
    setValidation(null);
    setSaveError(null);
    setModal({ mode: "edit", source });
  };

  const closeModal = () => {
    setModal(null);
    setSaveError(null);
    setValidation(null);
  };

  const handleValidate = async () => {
    if (!form.path.trim()) {
      setValidation({ valid: false, message: "Path cannot be empty." });
      return;
    }
    setValidating(true);
    setValidation(null);
    try {
      const result = await validateMediaSourcePath(form.path.trim());
      setValidation(result);
    } catch (e) {
      setValidation({ valid: false, message: String(e) });
    } finally { setValidating(false); }
  };

  const handleSave = async () => {
    if (!form.name.trim()) { setSaveError("Name is required."); return; }
    if (!form.path.trim()) { setSaveError("Path is required."); return; }
    setSaving(true);
    setSaveError(null);
    try {
      if (modal?.mode === "add") await createMediaSource(form);
      else if (modal?.mode === "edit" && modal.source) await updateMediaSource(modal.source.id, form);
      closeModal();
      await load();
    } catch (e) { setSaveError(String(e)); }
    finally { setSaving(false); }
  };

  const handleToggleEnable = async (source: LibraryRoot) => {
    try {
      await updateMediaSource(source.id, { enabled: !source.enabled });
      await load();
    } catch (e) { setError(`Failed to update: ${String(e)}`); }
  };

  const handleDelete = async (source: LibraryRoot) => {
    try {
      await deleteMediaSource(source.id);
      setConfirmDelete(null);
      await load();
    } catch (e) { setError(`Failed to delete: ${String(e)}`); }
  };

  const handleScanSource = async (source: LibraryRoot) => {
    setScanMsg(null);
    setScanning(source.id);
    try {
      const resp = await scanMediaSource(source.id);
      setScanMsg(resp.message);
    } catch (e) { setScanMsg(String(e)); }
    finally { setScanning(null); }
  };

  return (
    <div className="settings-page">
      {/* Header */}
      <div className="settings-header">
        <button className="btn-back" onClick={() => navigate("/")}>← Library</button>
        <h1>Settings</h1>
      </div>

      {/* Media Sources section */}
      <section className="settings-section">
        <div className="settings-section-header">
          <div>
            <h2>Media Sources</h2>
            <p className="settings-section-desc">
              Configure subfolders of <strong>/volume1</strong> that the scanner indexes for video files.
              <br />
              Browse <strong>/volume1</strong> and add subfolders — for example{" "}
              <code>sclad/Movies</code> or <code>video/GoPro</code>.
              <br />
              The root <code>/volume1</code> itself is never scanned automatically.
            </p>
          </div>
          <button className="btn-primary" onClick={openAdd}>+ Add Source</button>
        </div>

        {scanMsg && (
          <div className="settings-notice">
            {scanMsg}{" "}
            <button className="btn-link" onClick={() => setScanMsg(null)}>✕</button>
          </div>
        )}
        {error && (
          <div className="settings-error">
            {error}{" "}
            <button className="btn-link" onClick={() => setError(null)}>✕</button>
          </div>
        )}

        {loading ? (
          <div className="settings-loading">Loading…</div>
        ) : sources.length === 0 ? (
          <div className="settings-empty">
            <p>No media sources configured.</p>
            <p>
              Browse <strong>/volume1</strong> and add subfolders to scan.
              Use <strong>+ Add Source</strong> and click <strong>Browse /volume1</strong> to pick a folder.
            </p>
            <p className="form-hint">
              Example: add <code>sclad/Movies</code> — the app will scan{" "}
              <code>/media/sclad/Movies</code> (host: <code>/volume1/sclad/Movies</code>).
            </p>
          </div>
        ) : (
          <div className="settings-table-wrapper">
            <table className="settings-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Host path</th>
                  <th>Type</th>
                  <th>Enabled</th>
                  <th>Recursive</th>
                  <th>Priority</th>
                  <th>Videos</th>
                  <th>Last Scanned</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {sources.map((s) => (
                  <tr key={s.id} className={s.enabled ? "" : "row-disabled"}>
                    <td className="col-name">{s.name}</td>
                    <td className="col-path">
                      <code title={`Container: ${s.path}`}>
                        {s.display_path || s.path}
                      </code>
                    </td>
                    <td>{s.media_type}</td>
                    <td>
                      <button
                        className={`toggle-btn ${s.enabled ? "toggle-on" : "toggle-off"}`}
                        onClick={() => void handleToggleEnable(s)}
                        title={s.enabled ? "Disable source" : "Enable source"}
                      >
                        {s.enabled ? "✓ On" : "Off"}
                      </button>
                    </td>
                    <td>{s.recursive ? "Yes" : "No"}</td>
                    <td>{s.scan_priority}</td>
                    <td>{s.video_count}</td>
                    <td className="col-date">{formatDate(s.last_scanned_at)}</td>
                    <td>
                      <StatusBadge status={s.last_scan_status} />
                      {s.last_error && (
                        <span className="error-hint" title={s.last_error}> ⚠</span>
                      )}
                    </td>
                    <td className="col-actions">
                      <button className="btn-sm" onClick={() => openEdit(s)}>Edit</button>
                      <button
                        className="btn-sm btn-scan"
                        onClick={() => void handleScanSource(s)}
                        disabled={scanning === s.id || !s.enabled}
                        title={!s.enabled ? "Enable source to scan" : "Start scan"}
                      >
                        {scanning === s.id ? "…" : "Scan"}
                      </button>
                      <button className="btn-sm btn-danger" onClick={() => setConfirmDelete(s)}>
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Other settings sections */}
      <section className="settings-section settings-section-future">
        <h2>Maintenance</h2>
        <p className="settings-section-desc">
          Analyze and clean stale generated data: orphan HLS cache, thumbnails, duplicate records.
          <br />
          Original media files are <strong>never</strong> deleted by maintenance cleanup.
        </p>
        <button className="btn-secondary" onClick={() => navigate("/maintenance")}>
          Open Maintenance →
        </button>
      </section>

      <section className="settings-section settings-section-future">
        <h2>More Settings — Coming Soon</h2>
        <p className="settings-section-desc">
          Planned: Scan settings, HLS settings, Thumbnail settings, Cache settings.
        </p>
      </section>

      {/* Add / Edit modal */}
      {modal && (
        <div className="modal-overlay" onClick={closeModal}>
          <div className="modal-box" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>{modal.mode === "add" ? "Add Media Source" : "Edit Media Source"}</h3>
              <button className="modal-close" onClick={closeModal}>✕</button>
            </div>

            <div className="modal-body">
              {saveError && <div className="settings-error">{saveError}</div>}

              <label className="form-label">
                Name
                <input
                  className="form-input"
                  type="text"
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  placeholder="e.g. GoPro, Family, Movies"
                />
              </label>

              <label className="form-label">
                Path
                <div className="input-row">
                  <input
                    className="form-input"
                    type="text"
                    ref={pathRef}
                    value={form.path}
                    onChange={(e) => {
                      setForm((f) => ({ ...f, path: e.target.value }));
                      setValidation(null);
                    }}
                    placeholder="/media/sclad/Movies"
                  />
                  <button
                    className="btn-secondary btn-sm"
                    onClick={() => void openBrowse()}
                    type="button"
                  >
                    Browse /volume1
                  </button>
                  <button
                    className="btn-secondary btn-sm"
                    onClick={() => void handleValidate()}
                    disabled={validating}
                    type="button"
                  >
                    {validating ? "…" : "Validate"}
                  </button>
                </div>
                <span className="form-hint">
                  Select a subfolder of <code>/volume1</code> using <strong>Browse /volume1</strong>,
                  or enter the container path directly (e.g. <code>/media/sclad/Movies</code>).
                  The root <code>/volume1</code> itself cannot be added as a source.
                </span>
              </label>

              {validation && (
                <div className={`validation-result ${validation.valid ? "validation-ok" : "validation-fail"}`}>
                  {validation.valid ? "✓ " : "✗ "}
                  {validation.message}
                </div>
              )}

              <label className="form-label">
                Media type
                <select
                  className="form-input"
                  value={form.media_type ?? "video"}
                  onChange={(e) => setForm((f) => ({ ...f, media_type: e.target.value }))}
                >
                  <option value="video">Video</option>
                </select>
              </label>

              <label className="form-label form-label-inline">
                <input
                  type="checkbox"
                  checked={form.enabled ?? true}
                  onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.checked }))}
                />
                Enabled
              </label>

              <label className="form-label form-label-inline">
                <input
                  type="checkbox"
                  checked={form.recursive ?? true}
                  onChange={(e) => setForm((f) => ({ ...f, recursive: e.target.checked }))}
                />
                Recursive (scan sub-folders)
              </label>

              <label className="form-label">
                Scan priority (lower = scanned first)
                <input
                  className="form-input"
                  type="number"
                  min={1}
                  max={9999}
                  value={form.scan_priority ?? 100}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, scan_priority: parseInt(e.target.value, 10) || 100 }))
                  }
                />
              </label>
            </div>

            <div className="modal-footer">
              <button className="btn-secondary" onClick={closeModal} disabled={saving}>Cancel</button>
              <button className="btn-primary" onClick={() => void handleSave()} disabled={saving}>
                {saving ? "Saving…" : "Save"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Browse modal */}
      {browseOpen && (
        <div className="modal-overlay" onClick={() => setBrowseOpen(false)}>
          <div className="modal-box" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Browse /volume1</h3>
              <button className="modal-close" onClick={() => setBrowseOpen(false)}>✕</button>
            </div>
            <div className="modal-body">
              {/* Breadcrumb */}
              <div className="browse-breadcrumb">
                <span
                  className="browse-breadcrumb-item browse-breadcrumb-link"
                  onClick={() => void loadBrowse("").then(() => setBrowsePath(""))}
                >
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

              {browsePath && (
                <button className="btn-sm browse-up-btn" onClick={() => void handleBrowseUp()}>
                  ↑ Up
                </button>
              )}

              {browseLoading && <div className="settings-loading">Loading…</div>}
              {browseError && <div className="settings-error">{browseError}</div>}

              {!browseLoading && !browseError && browseItems.length === 0 && (
                <div className="settings-empty">No subfolders found here.</div>
              )}

              {!browseLoading && browseItems.length > 0 && (
                <ul className="browse-list">
                  {browseItems.map((item) => (
                    <li
                      key={item.relative_path}
                      className={`browse-item${item.blocked ? " browse-item-blocked" : item.already_added ? " browse-item-added" : ""}`}
                    >
                      <span
                        className="browse-item-name"
                        onClick={() => !item.blocked && void handleBrowseNavigate(item)}
                        title={item.blocked ? "Blocked (infrastructure)" : item.display_path}
                      >
                        📁 {item.name}
                        {item.blocked && <span className="browse-blocked-label"> (blocked)</span>}
                        {item.already_added && !item.blocked && (
                          <span className="browse-added-label"> (already added)</span>
                        )}
                      </span>
                      {!item.blocked && (
                        <button
                          className="btn-sm"
                          onClick={() => handleBrowseSelect(item)}
                          disabled={item.already_added}
                          title={item.already_added ? "Already a media source" : `Select ${item.display_path}`}
                        >
                          Select
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className="modal-footer">
              <button className="btn-secondary" onClick={() => setBrowseOpen(false)}>Close</button>
            </div>
          </div>
        </div>
      )}

      {/* Delete confirmation */}
      {confirmDelete && (
        <div className="modal-overlay" onClick={() => setConfirmDelete(null)}>
          <div className="modal-box modal-box-sm" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Remove Media Source</h3>
              <button className="modal-close" onClick={() => setConfirmDelete(null)}>✕</button>
            </div>
            <div className="modal-body">
              <p>Remove <strong>{confirmDelete.name}</strong> (<code>{confirmDelete.display_path || confirmDelete.path}</code>)?</p>
              <p className="form-hint"><strong>Original media files will NOT be deleted.</strong></p>
              <p className="form-hint">
                {confirmDelete.video_count} video(s) from this source will be hidden from the normal
                library and marked as <em>source_removed</em>. They remain in the database.
              </p>
              <p className="form-hint">
                Generated HLS cache is preserved. Use <strong>Settings → Maintenance</strong> to clean
                it up later if needed.
              </p>
            </div>
            <div className="modal-footer">
              <button className="btn-secondary" onClick={() => setConfirmDelete(null)}>Cancel</button>
              <button className="btn-danger" onClick={() => void handleDelete(confirmDelete)}>
                Remove Source
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

