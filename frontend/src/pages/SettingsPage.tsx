import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  browseMediaSources,
  cancelHlsBatch,
  clearMediaProfilePlaybackStatus,
  createLibraryHlsBatch,
  createMediaSource,
  deleteMediaSource,
  deleteVideo,
  getDuplicateGroups,
  getDuplicateStatus,
  getDuplicateSummary,
  getHealthStatus,
  getHlsBatch,
  getHlsGlobalStatus,
  getMediaProfiles,
  getMediaSources,
  getScheduledJobs,
  repairStaleHls,
  runScheduledJobNow,
  runScan,
  scanMediaSource,
  setMediaProfilePlaybackStatus,
  startDuplicateScan,
  updateScheduledJob,
  updateMediaSource,
  validateMediaSourcePath,
} from "../api/client";
import type {
  DuplicateGroup,
  DuplicateScanStatus,
  DuplicateSummary,
  HealthStatus,
  HlsBatchDetail,
  HlsGlobalStatus,
  LibraryRoot,
  LibraryRootIn,
  ManualPlaybackStatus,
  MediaProfileItem,
  MediaSourceBrowseItem,
  PathValidationResult,
  ScheduledJob,
} from "../types/video";
import { TagsManagementSection } from "../components/tags/TagsManagementSection";

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });
  } catch {
    return iso;
  }
}

function fmtBytes(bytes: number): string {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function asDailyTimeInput(value: string | null | undefined): string {
  if (!value) return "02:00";
  if (/^\d{2}:\d{2}$/.test(value)) return value;
  return "02:00";
}

function confidenceLabel(confidence: DuplicateGroup["confidence"]): string {
  if (confidence === "exact_metadata_match") return "Exact metadata match";
  if (confidence === "high") return "High";
  return "Medium";
}

function duplicateLibraryLabel(video: { library_root_id: number | null; library_root_name: string | null }): string {
  if (video.library_root_name && video.library_root_name.trim()) return video.library_root_name;
  if (video.library_root_id !== null) return `ID ${video.library_root_id}`;
  return "Unknown";
}

function StatusBadge({ status }: { status: string | null }) {
  if (!status) return <span className="badge badge-unknown">—</span>;
  const cls =
    status === "completed" || status === "completed_with_errors"
      ? "badge-ok"
      : status === "error"
        ? "badge-err"
        : status === "cancelled"
          ? "badge-warn"
          : "badge-unknown";
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

  // ── Media sources ───────────────────────────────────────────────────────
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
  const [scanAllBusy, setScanAllBusy] = useState(false);

  // Browse state
  const [browseOpen, setBrowseOpen] = useState(false);
  const [browsePath, setBrowsePath] = useState("");
  const [browseItems, setBrowseItems] = useState<MediaSourceBrowseItem[]>([]);
  const [browseLoading, setBrowseLoading] = useState(false);
  const [browseError, setBrowseError] = useState<string | null>(null);

  // ── HLS/Streaming ───────────────────────────────────────────────────────
  const [hlsGlobal, setHlsGlobal] = useState<HlsGlobalStatus | null>(null);
  const [hlsBatch, setHlsBatch] = useState<HlsBatchDetail | null>(null);
  const [hlsBusy, setHlsBusy] = useState(false);
  const [hlsCancelBusy, setHlsCancelBusy] = useState(false);
  const [hlsRepairBusy, setHlsRepairBusy] = useState(false);
  const [hlsMsg, setHlsMsg] = useState<string | null>(null);

  // ── Scheduler ───────────────────────────────────────────────────────────
  const [scheduledJobs, setScheduledJobs] = useState<ScheduledJob[]>([]);
  const [schedulerBusyKey, setSchedulerBusyKey] = useState<string | null>(null);
  const [schedulerMsg, setSchedulerMsg] = useState<string | null>(null);

  // ── Duplicates ──────────────────────────────────────────────────────────
  const [duplicateStatus, setDuplicateStatus] = useState<DuplicateScanStatus | null>(null);
  const [duplicateSummary, setDuplicateSummary] = useState<DuplicateSummary | null>(null);
  const [duplicateGroups, setDuplicateGroups] = useState<DuplicateGroup[]>([]);
  const [duplicateBusy, setDuplicateBusy] = useState(false);
  const [duplicateLoading, setDuplicateLoading] = useState(false);
  const [duplicateMsg, setDuplicateMsg] = useState<string | null>(null);
  const [deletingVideoId, setDeletingVideoId] = useState<number | null>(null);
  const [bulkDeleteBusy, setBulkDeleteBusy] = useState(false);
  const [selectedDuplicateIds, setSelectedDuplicateIds] = useState<Set<number>>(new Set());

  // ── Playback compatibility ──────────────────────────────────────────────
  const [mediaProfiles, setMediaProfiles] = useState<MediaProfileItem[]>([]);
  const [profileBusyId, setProfileBusyId] = useState<number | null>(null);
  const [profileMsg, setProfileMsg] = useState<string | null>(null);

  // ── System ────────���─────────────────────────────────────────────────────
  const [health, setHealth] = useState<HealthStatus | null>(null);

  const pathRef = useRef<HTMLInputElement>(null);

  const loadMediaSources = async () => {
    const data = await getMediaSources();
    setSources(data);
  };

  const loadHlsState = async () => {
    const global = await getHlsGlobalStatus();
    setHlsGlobal(global);
    if (global.active_batch_id !== null) {
      const batch = await getHlsBatch(global.active_batch_id, { include_items: false });
      setHlsBatch(batch);
    } else {
      setHlsBatch(null);
    }
  };

  const loadDuplicates = async () => {
    setDuplicateLoading(true);
    try {
      const [status, summary, groups] = await Promise.all([
        getDuplicateStatus(),
        getDuplicateSummary(),
        getDuplicateGroups(),
      ]);
      setDuplicateStatus(status);
      setDuplicateSummary(summary);
      setDuplicateGroups(groups);
      setSelectedDuplicateIds((prev) => {
        const validIds = new Set(groups.flatMap((group) => group.videos.map((video) => video.id)));
        const next = new Set<number>();
        prev.forEach((id) => {
          if (validIds.has(id)) next.add(id);
        });
        return next;
      });
    } finally {
      setDuplicateLoading(false);
    }
  };

  const loadCompatibility = async () => {
    setMediaProfiles(await getMediaProfiles());
  };

  const loadSystem = async () => {
    setHealth(await getHealthStatus());
  };

  const loadScheduler = async () => {
    setScheduledJobs(await getScheduledJobs());
  };

  const load = async () => {
    try {
      await Promise.all([
        loadMediaSources(),
        loadHlsState(),
        loadDuplicates(),
        loadCompatibility(),
        loadScheduler(),
        loadSystem(),
      ]);
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

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
    pathRef.current?.focus();
  };

  // ── Media source actions ────────────────────────────────────────────────

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
    } finally {
      setValidating(false);
    }
  };

  const handleSave = async () => {
    if (!form.name.trim()) {
      setSaveError("Name is required.");
      return;
    }
    if (!form.path.trim()) {
      setSaveError("Path is required.");
      return;
    }

    setSaving(true);
    setSaveError(null);
    try {
      if (modal?.mode === "add") {
        await createMediaSource(form);
      } else if (modal?.mode === "edit" && modal.source) {
        await updateMediaSource(modal.source.id, form);
      }
      closeModal();
      await loadMediaSources();
    } catch (e) {
      setSaveError(String(e));
    } finally {
      setSaving(false);
    }
  };

  const handleToggleEnable = async (source: LibraryRoot) => {
    try {
      await updateMediaSource(source.id, { enabled: !source.enabled });
      await loadMediaSources();
    } catch (e) {
      setError(`Failed to update: ${String(e)}`);
    }
  };

  const handleDelete = async (source: LibraryRoot) => {
    try {
      await deleteMediaSource(source.id);
      setConfirmDelete(null);
      await loadMediaSources();
    } catch (e) {
      setError(`Failed to delete: ${String(e)}`);
    }
  };

  const handleScanSource = async (source: LibraryRoot) => {
    setScanMsg(null);
    setScanning(source.id);
    try {
      const resp = await scanMediaSource(source.id);
      setScanMsg(resp.message);
    } catch (e) {
      setScanMsg(String(e));
    } finally {
      setScanning(null);
    }
  };

  const handleScanAll = async () => {
    setScanMsg(null);
    setScanAllBusy(true);
    try {
      const resp = await runScan();
      setScanMsg(resp.message);
    } catch (e) {
      setScanMsg(String(e));
    } finally {
      setScanAllBusy(false);
    }
  };

  // ── HLS actions ────────────────────────────────────────────────────────

  const handleStartHlsForAllMissing = async () => {
    setHlsBusy(true);
    setHlsMsg(null);
    try {
      const response = await createLibraryHlsBatch({ skip_existing: true, force: false, only_missing_hls: true });
      setHlsMsg(response.message);
      await loadHlsState();
    } catch (e) {
      setHlsMsg(String(e));
    } finally {
      setHlsBusy(false);
    }
  };

  const handleCancelHlsBatch = async () => {
    if (!hlsBatch) return;
    setHlsCancelBusy(true);
    try {
      await cancelHlsBatch(hlsBatch.id);
      await loadHlsState();
      setHlsMsg("HLS batch cancellation requested.");
    } catch (e) {
      setHlsMsg(String(e));
    } finally {
      setHlsCancelBusy(false);
    }
  };

  const handleRepairHls = async () => {
    setHlsRepairBusy(true);
    try {
      const res = await repairStaleHls();
      setHlsMsg(
        `Repair complete: checked ${res.checked}, repaired ${res.db_repaired_to_completed}, invalidated ${res.stale_completed_invalidated}.`
      );
      await loadHlsState();
    } catch (e) {
      setHlsMsg(String(e));
    } finally {
      setHlsRepairBusy(false);
    }
  };

  const libraryScanJob = scheduledJobs.find((job) => job.job_type === "library_scan") ?? null;
  const hlsMissingJob = scheduledJobs.find((job) => job.job_type === "hls_prepare_missing") ?? null;

  const handleSaveScheduledJob = async (job: ScheduledJob, patch: Partial<Pick<ScheduledJob, "enabled" | "time_of_day">>) => {
    const busyKey = `save-${job.id}`;
    setSchedulerBusyKey(busyKey);
    setSchedulerMsg(null);
    try {
      await updateScheduledJob(job.id, {
        enabled: patch.enabled ?? job.enabled,
        schedule_type: "daily",
        time_of_day: patch.time_of_day ?? asDailyTimeInput(job.time_of_day),
      });
      await loadScheduler();
      setSchedulerMsg(`${job.name} schedule updated.`);
    } catch (e) {
      setSchedulerMsg(String(e));
    } finally {
      setSchedulerBusyKey(null);
    }
  };

  const handleRunScheduledJobNow = async (job: ScheduledJob) => {
    const busyKey = `run-${job.id}`;
    setSchedulerBusyKey(busyKey);
    setSchedulerMsg(null);
    try {
      const result = await runScheduledJobNow(job.id);
      if (result.status === "started") {
        setSchedulerMsg(`${job.name}: started.`);
      } else {
        setSchedulerMsg(`${job.name}: ${result.reason ?? "skipped"}`);
      }
      await Promise.all([loadScheduler(), loadHlsState()]);
    } catch (e) {
      setSchedulerMsg(String(e));
    } finally {
      setSchedulerBusyKey(null);
    }
  };

  // ── Duplicates actions ─────────────────────────────────────────────────────────

  const handleStartDuplicateScan = async () => {
    setDuplicateBusy(true);
    setDuplicateMsg(null);
    try {
      await startDuplicateScan();
      await loadDuplicates();
      setDuplicateMsg("Duplicate scan started.");
    } catch (e) {
      setDuplicateMsg(String(e));
    } finally {
      setDuplicateBusy(false);
    }
  };

  const handleDeleteDuplicateVideo = async (videoId: number) => {
    const ok = window.confirm("Delete this video from source and index?");
    if (!ok) return;
    try {
      setDeletingVideoId(videoId);
      await deleteVideo(videoId);
      setSelectedDuplicateIds((prev) => {
        const next = new Set(prev);
        next.delete(videoId);
        return next;
      });
      await loadDuplicates();
      setDuplicateMsg("Video deleted.");
    } catch (e) {
      setDuplicateMsg(String(e));
    } finally {
      setDeletingVideoId(null);
    }
  };

  const handleToggleDuplicateSelection = (videoId: number, selected: boolean) => {
    setSelectedDuplicateIds((prev) => {
      const next = new Set(prev);
      if (selected) next.add(videoId);
      else next.delete(videoId);
      return next;
    });
  };

  const handleToggleGroupSelection = (group: DuplicateGroup, selected: boolean) => {
    setSelectedDuplicateIds((prev) => {
      const next = new Set(prev);
      for (const video of group.videos) {
        if (selected) next.add(video.id);
        else next.delete(video.id);
      }
      return next;
    });
  };

  const handleDeleteSelectedDuplicates = async () => {
    const selectedIds = Array.from(selectedDuplicateIds);
    if (selectedIds.length === 0) return;
    const ok = window.confirm(`Delete ${selectedIds.length} selected duplicate video(s) from source and index?`);
    if (!ok) return;

    setBulkDeleteBusy(true);
    setDuplicateMsg(null);
    const errors: string[] = [];
    let deletedCount = 0;

    try {
      for (const videoId of selectedIds) {
        try {
          await deleteVideo(videoId);
          deletedCount += 1;
        } catch (e) {
          errors.push(`ID ${videoId}: ${String(e)}`);
        }
      }
      setSelectedDuplicateIds(new Set());
      await loadDuplicates();
      if (errors.length > 0) {
        setDuplicateMsg(`Deleted ${deletedCount} video(s). ${errors.length} failed: ${errors.join("; ")}`);
      } else {
        setDuplicateMsg(`Deleted ${deletedCount} selected video(s).`);
      }
    } finally {
      setBulkDeleteBusy(false);
    }
  };

  const selectedDuplicateCount = selectedDuplicateIds.size;
  const selectedDuplicateSize = duplicateGroups.reduce((sum, group) => {
    return sum + group.videos.reduce((groupSum, video) => {
      return selectedDuplicateIds.has(video.id) ? groupSum + video.size : groupSum;
    }, 0);
  }, 0);

  // ── Playback compatibility actions ──────────────────────────────────────

  const handleSetProfileStatus = async (profileId: number, status: ManualPlaybackStatus) => {
    try {
      setProfileBusyId(profileId);
      await setMediaProfilePlaybackStatus(profileId, status);
      await loadCompatibility();
      setProfileMsg("Profile updated.");
    } catch (e) {
      setProfileMsg(String(e));
    } finally {
      setProfileBusyId(null);
    }
  };

  const handleClearProfileStatus = async (profileId: number) => {
    try {
      setProfileBusyId(profileId);
      await clearMediaProfilePlaybackStatus(profileId);
      await loadCompatibility();
      setProfileMsg("Manual override cleared.");
    } catch (e) {
      setProfileMsg(String(e));
    } finally {
      setProfileBusyId(null);
    }
  };

  return (
    <div className="settings-page settings-page-ops">
      <div className="settings-header">
        <button className="btn-back" onClick={() => navigate("/")}>← Library</button>
        <h1>Settings</h1>
      </div>

      {error && <div className="settings-error">{error}</div>}

      {/* Media Sources */}
      <section className="settings-section" id="media-sources">
        <div className="settings-section-header">
          <div>
            <h2>Media Sources</h2>
            <p className="settings-section-desc">
              Configure subfolders of <strong>/volume1</strong> for scanning.
            </p>
          </div>
          <div className="settings-inline-actions">
            <button className="btn-secondary" onClick={() => void handleScanAll()} disabled={scanAllBusy}>
              {scanAllBusy ? "Starting..." : "Scan Library"}
            </button>
            <button className="btn-primary" onClick={openAdd}>+ Add Source</button>
          </div>
        </div>

        {scanMsg && <div className="settings-notice">{scanMsg}</div>}

        {loading ? (
          <div className="settings-loading">Loading...</div>
        ) : sources.length === 0 ? (
          <div className="settings-empty">
            No media sources configured. Browse <strong>/volume1</strong> and add subfolders to scan.
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
                    <td>{s.name}</td>
                    <td><code title={`Container: ${s.path}`}>{s.display_path || s.path}</code></td>
                    <td>{s.media_type === "photo" ? "Photo" : s.media_type === "mixed" ? "Mixed (legacy)" : "Video"}</td>
                    <td>
                      <button
                        className={`toggle-btn ${s.enabled ? "toggle-on" : "toggle-off"}`}
                        onClick={() => void handleToggleEnable(s)}
                      >
                        {s.enabled ? "✓ On" : "Off"}
                      </button>
                    </td>
                    <td>{s.recursive ? "Yes" : "No"}</td>
                    <td>{s.scan_priority}</td>
                    <td>{s.video_count}</td>
                    <td>{formatDate(s.last_scanned_at)}</td>
                    <td><StatusBadge status={s.last_scan_status} /></td>
                    <td className="col-actions">
                      <button className="btn-sm" onClick={() => openEdit(s)}>Edit</button>
                      <button
                        className="btn-sm btn-scan"
                        onClick={() => void handleScanSource(s)}
                        disabled={scanning === s.id || !s.enabled}
                      >
                        {scanning === s.id ? "..." : "Scan"}
                      </button>
                      <button className="btn-sm btn-danger" onClick={() => setConfirmDelete(s)}>Delete</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* HLS / Streaming */}
      <section className="settings-section" id="hls-streaming">
        <div className="settings-section-header">
          <div>
            <h2>HLS / Streaming</h2>
            <p className="settings-section-desc">
              Start HLS generation for missing videos and repair stale HLS DB state. Default generation profiles: 480p and 720p.
            </p>
          </div>
          <div className="settings-inline-actions">
            <button className="btn-secondary" onClick={() => void handleRepairHls()} disabled={hlsRepairBusy}>
              {hlsRepairBusy ? "Repairing..." : "Repair HLS State"}
            </button>
            <button className="btn-primary" onClick={() => void handleStartHlsForAllMissing()} disabled={hlsBusy}>
              {hlsBusy ? "Starting..." : "Prepare HLS for all missing"}
            </button>
          </div>
        </div>

        {hlsMsg && <div className="settings-notice">{hlsMsg}</div>}

        <div className="settings-notice">
          Generated HLS profiles: <strong>480p, 720p</strong>. 1080p is not generated by default. Original playback remains available for maximum quality.
        </div>

        <div className="settings-kv-grid">
          <div><strong>Running jobs:</strong> {hlsGlobal?.running ?? 0}</div>
          <div><strong>Max concurrent:</strong> {hlsGlobal?.max_concurrent ?? 0}</div>
          <div><strong>Queued jobs:</strong> {hlsGlobal?.queued_jobs ?? 0}</div>
          <div><strong>Recent completed:</strong> {hlsGlobal?.recent_completed ?? 0}</div>
          <div><strong>Recent failed:</strong> {hlsGlobal?.recent_failed ?? 0}</div>
        </div>

        {hlsBatch && (
          <div className="settings-notice">
            <strong>Active batch #{hlsBatch.id}</strong> - {hlsBatch.status} - {Math.round(hlsBatch.progress_percent)}%
            {hlsBatch.current_video ? ` - current: ${hlsBatch.current_video.title}` : ""}
            {(hlsBatch.status === "queued" || hlsBatch.status === "running") && (
              <button className="btn-danger btn-sm" style={{ marginLeft: 8 }} onClick={() => void handleCancelHlsBatch()} disabled={hlsCancelBusy}>
                {hlsCancelBusy ? "Stopping..." : "Stop batch"}
              </button>
            )}
          </div>
        )}
      </section>

      {/* Scheduler */}
      <section className="settings-section" id="scheduler">
        <div className="settings-section-header">
          <div>
            <h2>Scheduler</h2>
            <p className="settings-section-desc">
              Daily background jobs use container local time. Jobs are disabled by default and skip when related processes are already running.
            </p>
          </div>
          <button className="btn-secondary" onClick={() => void loadScheduler()}>Refresh</button>
        </div>

        {schedulerMsg && <div className="settings-notice">{schedulerMsg}</div>}

        {[libraryScanJob, hlsMissingJob].filter(Boolean).map((job) => {
          const current = job as ScheduledJob;
          const saveBusy = schedulerBusyKey === `save-${current.id}`;
          const runBusy = schedulerBusyKey === `run-${current.id}`;
          return (
            <div key={current.id} className="settings-notice" style={{ display: "block" }}>
              <div className="settings-section-header" style={{ marginBottom: 8 }}>
                <div>
                  <strong>{current.name}</strong>
                  {current.job_type === "hls_prepare_missing" ? (
                    <p className="settings-section-desc" style={{ margin: "4px 0 0" }}>
                      Uses 480p and 720p profiles. Existing HLS is skipped.
                    </p>
                  ) : null}
                </div>
                <button
                  className="btn-secondary"
                  onClick={() => void handleRunScheduledJobNow(current)}
                  disabled={runBusy}
                >
                  {runBusy ? "Running..." : "Run now"}
                </button>
              </div>

              <div className="settings-kv-grid">
                <div>
                  <strong>Enabled:</strong>{" "}
                  <button
                    className={`toggle-btn ${current.enabled ? "toggle-on" : "toggle-off"}`}
                    onClick={() => void handleSaveScheduledJob(current, { enabled: !current.enabled })}
                    disabled={saveBusy}
                  >
                    {current.enabled ? "✓ On" : "Off"}
                  </button>
                </div>
                <div>
                  <strong>Daily time:</strong>{" "}
                  <input
                    type="time"
                    value={asDailyTimeInput(current.time_of_day)}
                    onChange={(e) => void handleSaveScheduledJob(current, { time_of_day: e.target.value })}
                    disabled={saveBusy}
                  />
                </div>
                <div><strong>Last run:</strong> {formatDate(current.last_run_at)}</div>
                <div><strong>Next run:</strong> {formatDate(current.next_run_at)}</div>
                <div><strong>Last status:</strong> {current.last_status ?? "—"}</div>
                <div><strong>Last error:</strong> {current.last_error ?? "—"}</div>
              </div>
            </div>
          );
        })}
      </section>

      {/* Duplicates */}
      <section className="settings-section" id="duplicates">
        <div className="settings-section-header">
          <div>
            <h2>Duplicates</h2>
            <p className="settings-section-desc">
              Run duplicate scan, review candidate groups, and delete selected duplicate files.
            </p>
          </div>
          <button className="btn-primary" onClick={() => void handleStartDuplicateScan()} disabled={duplicateBusy || duplicateStatus?.status === "running"}>
            {duplicateBusy || duplicateStatus?.status === "running" ? "Scanning..." : "Scan Duplicates"}
          </button>
        </div>

        {duplicateMsg && <div className="settings-notice">{duplicateMsg}</div>}

        <div className="settings-kv-grid">
          <div><strong>Status:</strong> {duplicateStatus?.status ?? "idle"}</div>
          <div><strong>Groups:</strong> {duplicateSummary?.candidate_groups_found ?? 0}</div>
          <div><strong>Candidates:</strong> {duplicateSummary?.duplicate_candidates_found ?? 0}</div>
          <div><strong>Potential saving:</strong> {fmtBytes(duplicateSummary?.potential_saving ?? 0)}</div>
        </div>

        {duplicateLoading ? (
          <div className="settings-loading">Loading duplicate groups...</div>
        ) : duplicateGroups.length === 0 ? (
          <div className="settings-empty">No duplicate groups yet.</div>
        ) : (
          <div className="duplicate-groups">
            <div className="duplicates-bulk-actions">
              <div className="duplicates-selected-stats">
                <strong>Selected:</strong> {selectedDuplicateCount} file(s), {fmtBytes(selectedDuplicateSize)}
              </div>
              <div className="duplicates-bulk-buttons">
                <button className="btn-secondary" onClick={() => setSelectedDuplicateIds(new Set())} disabled={selectedDuplicateCount === 0 || bulkDeleteBusy}>
                  Clear selection
                </button>
                <button className="btn-danger" onClick={() => void handleDeleteSelectedDuplicates()} disabled={selectedDuplicateCount === 0 || bulkDeleteBusy}>
                  {bulkDeleteBusy ? "Deleting..." : "Delete selected"}
                </button>
              </div>
            </div>

            {duplicateGroups.map((group, index) => (
              <section key={group.group_id} className="duplicate-group-card">
                <div className="duplicate-group-header">
                  <div>
                    <h3>Group {index + 1}</h3>
                    <p className="duplicate-reason">{group.reason}</p>
                  </div>
                  <label className="form-label form-label-inline" style={{ margin: 0 }}>
                    <input
                      type="checkbox"
                      checked={group.videos.every((video) => selectedDuplicateIds.has(video.id))}
                      onChange={(e) => handleToggleGroupSelection(group, e.target.checked)}
                    />
                    Select group
                  </label>
                  <span className={`duplicate-confidence badge-${group.confidence}`}>{confidenceLabel(group.confidence)}</span>
                </div>

                <div className="duplicate-fingerprint-grid">
                  <div><strong>Count:</strong> {group.candidate_count}</div>
                  <div><strong>Total size:</strong> {fmtBytes(group.total_size)}</div>
                  <div><strong>Potential saving:</strong> {fmtBytes(group.potential_saving)}</div>
                  <div>
                    <strong>Libraries:</strong>{" "}
                    {Array.from(new Set(group.videos.map((video) => duplicateLibraryLabel(video)))).join(", ")}
                  </div>
                </div>

                <div className="duplicate-video-list">
                  {group.videos.map((video) => (
                    <article key={video.id} className="duplicate-video-item">
                      <label className="duplicate-video-select" title="Select duplicate for bulk delete">
                        <input
                          type="checkbox"
                          checked={selectedDuplicateIds.has(video.id)}
                          onChange={(e) => handleToggleDuplicateSelection(video.id, e.target.checked)}
                        />
                      </label>
                      <div className="duplicate-video-thumb">
                        {video.thumbnail_url ? <img src={video.thumbnail_url} alt={video.title} loading="lazy" /> : <div className="thumb placeholder">No Thumbnail</div>}
                      </div>
                      <div className="duplicate-video-body">
                        <a href={video.watch_url} target="_blank" rel="noopener noreferrer" className="duplicate-video-link">
                          {video.title}
                        </a>
                        <p><strong>Library:</strong> {duplicateLibraryLabel(video)}</p>
                        <p>{video.relative_path}</p>
                        <p>{fmtBytes(video.size)}</p>
                        <button className="btn-danger duplicate-delete-btn" onClick={() => void handleDeleteDuplicateVideo(video.id)} disabled={deletingVideoId === video.id || bulkDeleteBusy}>
                          {deletingVideoId === video.id ? "Deleting..." : "Delete this video"}
                        </button>
                      </div>
                    </article>
                  ))}
                </div>
              </section>
            ))}
          </div>
        )}
      </section>

      {/* Playback Compatibility */}
      <section className="settings-section" id="playback-compatibility">
        <div className="settings-section-header">
          <div>
            <h2>Playback Compatibility</h2>
            <p className="settings-section-desc">
              Review media profiles and mark what plays correctly in your browser/devices.
            </p>
          </div>
          <button className="btn-secondary" onClick={() => void loadCompatibility()}>Refresh</button>
        </div>

        {profileMsg && <div className="settings-notice">{profileMsg}</div>}

        {mediaProfiles.length === 0 ? (
          <div className="settings-empty">No media profiles yet. Scan the library first.</div>
        ) : (
          <div className="settings-table-wrapper">
            <table className="settings-table">
              <thead>
                <tr>
                  <th>Extension</th>
                  <th>Video / Audio</th>
                  <th>Files</th>
                  <th>Auto</th>
                  <th>Manual</th>
                  <th>Effective</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {mediaProfiles.map((profile) => (
                  <tr key={profile.id}>
                    <td>{profile.extension}</td>
                    <td>{profile.video_codec} / {profile.audio_codec}</td>
                    <td>{profile.files_count}</td>
                    <td>{profile.auto_compatibility_status}</td>
                    <td>{profile.manual_playback_status ?? "—"}</td>
                    <td>{profile.effective_compatibility_status}</td>
                    <td className="col-actions">
                      <button className="btn-sm" disabled={profileBusyId === profile.id} onClick={() => void handleSetProfileStatus(profile.id, "playable")}>Playable</button>
                      <button className="btn-sm" disabled={profileBusyId === profile.id} onClick={() => void handleSetProfileStatus(profile.id, "partially_playable")}>Partial</button>
                      <button className="btn-sm" disabled={profileBusyId === profile.id} onClick={() => void handleSetProfileStatus(profile.id, "not_playable")}>Not playable</button>
                      <button className="btn-sm btn-secondary" disabled={profileBusyId === profile.id} onClick={() => void handleClearProfileStatus(profile.id)}>Clear</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Maintenance */}
      <section className="settings-section" id="maintenance">
        <div className="settings-section-header">
          <div>
            <h2>Maintenance</h2>
            <p className="settings-section-desc">
              Cleanup stale generated data and repair state mismatches.
            </p>
          </div>
          <button className="btn-secondary" onClick={() => navigate("/maintenance")}>Open Maintenance →</button>
        </div>
      </section>

      <TagsManagementSection onChanged={() => void load()} />

      {/* System */}
      <section className="settings-section" id="system-runtime">
        <div className="settings-section-header">
          <div>
            <h2>System / Runtime</h2>
            <p className="settings-section-desc">Container runtime paths and health status.</p>
          </div>
          <button className="btn-secondary" onClick={() => void loadSystem()}>Refresh</button>
        </div>

        {!health ? (
          <div className="settings-loading">Loading...</div>
        ) : (
          <>
            <div className="settings-kv-grid"><div><strong>Health:</strong> {health.status}</div></div>
            <div className="settings-table-wrapper">
              <table className="settings-table">
                <thead>
                  <tr><th>Runtime key</th><th>Path</th></tr>
                </thead>
                <tbody>
                  {Object.entries(health.runtime_dirs).map(([key, value]) => (
                    <tr key={key}>
                      <td>{key}</td>
                      <td><code>{value}</code></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
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
                  placeholder="e.g. Movies"
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
                  <button className="btn-secondary btn-sm" onClick={() => void openBrowse()} type="button">Browse /volume1</button>
                  <button className="btn-secondary btn-sm" onClick={() => void handleValidate()} disabled={validating} type="button">
                    {validating ? "..." : "Validate"}
                  </button>
                </div>
                <span className="form-hint">
                  Select folders relative to /volume1. Example: sclad/Movies. The mounted root /volume1 itself is not scanned.
                </span>
              </label>

              {validation && (
                <div className={`validation-result ${validation.valid ? "validation-ok" : "validation-fail"}`}>
                  {validation.valid ? "✓ " : "✗ "}{validation.message}
                </div>
              )}

              <label className="form-label">
                Source type
                <select
                  className="form-input"
                  value={form.media_type ?? "video"}
                  onChange={(e) => setForm((f) => ({ ...f, media_type: e.target.value as "video" | "photo" }))}
                >
                  <option value="video">Video</option>
                  <option value="photo">Photo</option>
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
                Recursive
              </label>
            </div>

            <div className="modal-footer">
              <button className="btn-secondary" onClick={closeModal} disabled={saving}>Cancel</button>
              <button className="btn-primary" onClick={() => void handleSave()} disabled={saving}>{saving ? "Saving..." : "Save"}</button>
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
              <div className="browse-breadcrumb">
                <span className="browse-breadcrumb-item browse-breadcrumb-link" onClick={() => void loadBrowse("").then(() => setBrowsePath(""))}>
                  /volume1
                </span>
                {browsePath.split("/").filter(Boolean).map((part, i, arr) => {
                  const partial = arr.slice(0, i + 1).join("/");
                  return (
                    <span key={partial}>
                      {" / "}
                      <span className="browse-breadcrumb-item browse-breadcrumb-link" onClick={() => void loadBrowse(partial).then(() => setBrowsePath(partial))}>
                        {part}
                      </span>
                    </span>
                  );
                })}
              </div>

              {browsePath && <button className="btn-sm browse-up-btn" onClick={() => void handleBrowseUp()}>↑ Up</button>}
              {browseLoading && <div className="settings-loading">Loading...</div>}
              {browseError && <div className="settings-error">{browseError}</div>}

              {!browseLoading && !browseError && browseItems.length === 0 && <div className="settings-empty">No subfolders found.</div>}

              {!browseLoading && browseItems.length > 0 && (
                <ul className="browse-list">
                  {browseItems.map((item) => (
                    <li key={item.relative_path} className={`browse-item${item.blocked ? " browse-item-blocked" : item.already_added ? " browse-item-added" : ""}`}>
                      <span className="browse-item-name" onClick={() => !item.blocked && void handleBrowseNavigate(item)} title={item.blocked ? "Blocked" : item.display_path}>
                        📁 {item.name}
                        {item.blocked && <span className="browse-blocked-label"> (blocked)</span>}
                        {item.already_added && !item.blocked && <span className="browse-added-label"> (already added)</span>}
                      </span>
                      {!item.blocked && (
                        <button className="btn-sm" onClick={() => handleBrowseSelect(item)} disabled={item.already_added}>Select</button>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className="modal-footer"><button className="btn-secondary" onClick={() => setBrowseOpen(false)}>Close</button></div>
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
            </div>
            <div className="modal-footer">
              <button className="btn-secondary" onClick={() => setConfirmDelete(null)}>Cancel</button>
              <button className="btn-danger" onClick={() => void handleDelete(confirmDelete)}>Remove Source</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

