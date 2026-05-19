import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  applyCleanupPlan,
  createCleanupPlan,
  getMaintenanceSummary,
  repairStaleHls,
} from "../api/client";
import type { CleanupApplyResult, CleanupItem, CleanupPlan, CleanupSummary } from "../types/video";

function fmtBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = bytes;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

type IncludeOptions = {
  orphan_hls_folders: boolean;
  hls_db_records_missing_files: boolean;
  orphan_thumbnails: boolean;
  stale_hls_jobs: boolean;
  stale_duplicate_records: boolean;
  source_removed_hls: boolean;
  missing_video_hls: boolean;
};

const DEFAULT_INCLUDE: IncludeOptions = {
  orphan_hls_folders: true,
  hls_db_records_missing_files: true,
  orphan_thumbnails: true,
  stale_hls_jobs: true,
  stale_duplicate_records: true,
  source_removed_hls: false,
  missing_video_hls: false,
};

const OPTION_LABELS: Record<keyof IncludeOptions, string> = {
  orphan_hls_folders: "Orphan HLS folders (no matching video)",
  hls_db_records_missing_files: "HLS DB records with missing files",
  orphan_thumbnails: "Orphan thumbnail files",
  stale_hls_jobs: "Stale HLS jobs (stuck > 2h)",
  stale_duplicate_records: "Stale duplicate records",
  source_removed_hls: "⚠ HLS cache for source-removed videos",
  missing_video_hls: "⚠ HLS cache for missing-file videos",
};

export function MaintenancePage() {
  const navigate = useNavigate();
  const [summary, setSummary] = useState<CleanupSummary | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);

  const [include, setInclude] = useState<IncludeOptions>(DEFAULT_INCLUDE);

  const [plan, setPlan] = useState<CleanupPlan | null>(null);
  const [planLoading, setPlanLoading] = useState(false);
  const [planError, setPlanError] = useState<string | null>(null);

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [applying, setApplying] = useState(false);
  const [applyResult, setApplyResult] = useState<CleanupApplyResult | null>(null);
  const [applyError, setApplyError] = useState<string | null>(null);

  const [repairing, setRepairing] = useState(false);
  const [repairMsg, setRepairMsg] = useState<string | null>(null);

  const loadSummary = async () => {
    setSummaryLoading(true);
    setSummaryError(null);
    try {
      const data = await getMaintenanceSummary();
      setSummary(data);
    } catch (e) {
      setSummaryError(String(e));
    } finally {
      setSummaryLoading(false);
    }
  };

  useEffect(() => { void loadSummary(); }, []);

  const handleAnalyze = async () => {
    setPlanLoading(true);
    setPlanError(null);
    setPlan(null);
    setApplyResult(null);
    try {
      const p = await createCleanupPlan(include);
      setPlan(p);
      setSelectedIds(new Set(p.items.filter((i) => i.safe).map((i) => i.item_id)));
    } catch (e) {
      setPlanError(String(e));
    } finally {
      setPlanLoading(false);
    }
  };

  const handleRepair = async () => {
    setRepairing(true);
    setRepairMsg(null);
    try {
      const res = await repairStaleHls();
      setRepairMsg(
        `Repair complete. Checked: ${res.checked}, DB repaired: ${res.db_repaired_to_completed}, Stale invalidated: ${res.stale_completed_invalidated}.`
      );
      void loadSummary();
    } catch (e) {
      setRepairMsg(`Repair failed: ${String(e)}`);
    } finally {
      setRepairing(false);
    }
  };

  const toggleItem = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAll = () => {
    if (!plan) return;
    if (selectedIds.size === plan.items.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(plan.items.map((i) => i.item_id)));
    }
  };

  const selectedSize = plan
    ? plan.items.filter((i) => selectedIds.has(i.item_id)).reduce((acc, i) => acc + i.size, 0)
    : 0;

  const handleApply = async () => {
    if (!plan) return;
    setApplying(true);
    setApplyError(null);
    try {
      const result = await applyCleanupPlan(plan.plan_id, [...selectedIds]);
      setApplyResult(result);
      setConfirmOpen(false);
      setPlan(null);
      void loadSummary();
    } catch (e) {
      setApplyError(String(e));
    } finally {
      setApplying(false);
    }
  };

  const groupedItems = (items: CleanupItem[]) => {
    const groups: Record<string, CleanupItem[]> = {};
    for (const item of items) {
      if (!groups[item.type]) groups[item.type] = [];
      groups[item.type].push(item);
    }
    return groups;
  };

  return (
    <div className="settings-page">
      <div className="settings-header">
        <button className="btn-back" onClick={() => navigate("/settings")}>
          ← Settings
        </button>
        <h1>Maintenance</h1>
      </div>

      {/* Summary */}
      <section className="settings-section">
        <div className="settings-section-header">
          <div>
            <h2>Cleanup Overview</h2>
            <p className="settings-section-desc">
              Analyze stale generated data (HLS cache, thumbnails, duplicate records).{" "}
              <strong>Original media files are never deleted by maintenance cleanup.</strong>
            </p>
          </div>
          <button className="btn-secondary" onClick={() => void loadSummary()} disabled={summaryLoading}>
            {summaryLoading ? "Analyzing…" : "↺ Refresh Summary"}
          </button>
        </div>

        {summaryError && <div className="settings-error">{summaryError}</div>}

        {summary && (
          <div className="maintenance-summary-grid">
            <div className="summary-card">
              <h3>HLS Cache</h3>
              <div className="summary-rows">
                <span>Valid HLS</span><strong>{summary.hls.valid_hls}</strong>
                <span>Orphan folders</span><strong className={summary.hls.orphan_hls_folders > 0 ? "warn" : ""}>{summary.hls.orphan_hls_folders} ({fmtBytes(summary.hls.orphan_hls_size)})</strong>
                <span>DB completed / files missing</span><strong className={summary.hls.db_completed_but_files_missing > 0 ? "warn" : ""}>{summary.hls.db_completed_but_files_missing}</strong>
                <span>Files exist / DB missing</span><strong className={summary.hls.files_exist_but_db_missing > 0 ? "warn" : ""}>{summary.hls.files_exist_but_db_missing}</strong>
                <span>Stale running jobs</span><strong className={summary.hls.stale_running_jobs > 0 ? "warn" : ""}>{summary.hls.stale_running_jobs}</strong>
                <span>Old failed jobs</span><strong>{summary.hls.failed_jobs_old}</strong>
              </div>
            </div>

            <div className="summary-card">
              <h3>Videos</h3>
              <div className="summary-rows">
                <span>Available</span><strong>{summary.videos.available}</strong>
                <span>Missing source file</span><strong className={summary.videos.missing > 0 ? "warn" : ""}>{summary.videos.missing}</strong>
                <span>Source disabled</span><strong>{summary.videos.source_disabled}</strong>
                <span>Source removed</span><strong className={summary.videos.source_removed > 0 ? "warn" : ""}>{summary.videos.source_removed}</strong>
              </div>
            </div>

            <div className="summary-card">
              <h3>Thumbnails</h3>
              <div className="summary-rows">
                <span>Orphan thumbnails</span><strong className={summary.thumbnails.orphan_thumbnails > 0 ? "warn" : ""}>{summary.thumbnails.orphan_thumbnails}</strong>
                <span>Orphan size</span><strong>{fmtBytes(summary.thumbnails.orphan_thumbnails_size)}</strong>
              </div>
            </div>

            <div className="summary-card">
              <h3>Duplicates</h3>
              <div className="summary-rows">
                <span>Stale items</span><strong className={summary.duplicates.stale_duplicate_items > 0 ? "warn" : ""}>{summary.duplicates.stale_duplicate_items}</strong>
                <span>Stale groups</span><strong className={summary.duplicates.stale_duplicate_groups > 0 ? "warn" : ""}>{summary.duplicates.stale_duplicate_groups}</strong>
              </div>
            </div>

            <div className="summary-card summary-card-total">
              <h3>Potential Cleanup</h3>
              <div className="summary-potential">{fmtBytes(summary.potential_cleanup_size)}</div>
              <p className="settings-section-desc">Safe orphan HLS + thumbnails only</p>
            </div>
          </div>
        )}
      </section>

      {/* Repair HLS */}
      <section className="settings-section">
        <div className="settings-section-header">
          <div>
            <h2>Repair HLS State</h2>
            <p className="settings-section-desc">
              Reconcile DB records with actual HLS files on disk.
              Repair fixes inconsistencies <em>without deleting any files</em>.
            </p>
          </div>
          <button className="btn-secondary" onClick={() => void handleRepair()} disabled={repairing}>
            {repairing ? "Repairing…" : "↺ Repair HLS State"}
          </button>
        </div>
        {repairMsg && <div className="settings-notice">{repairMsg}</div>}
      </section>

      {/* Cleanup Plan */}
      <section className="settings-section">
        <div className="settings-section-header">
          <div>
            <h2>Create Cleanup Plan</h2>
            <p className="settings-section-desc">
              Select categories to include. A dry-run plan is generated first — no files are deleted until you confirm.
            </p>
          </div>
          <button className="btn-primary" onClick={() => void handleAnalyze()} disabled={planLoading}>
            {planLoading ? "Analyzing…" : "Analyze Cleanup"}
          </button>
        </div>

        <div className="maintenance-options">
          {(Object.entries(OPTION_LABELS) as [keyof IncludeOptions, string][]).map(([key, label]) => {
            const isRisky = key === "source_removed_hls" || key === "missing_video_hls";
            return (
              <label key={key} className={`form-label form-label-inline ${isRisky ? "label-risky" : ""}`}>
                <input
                  type="checkbox"
                  checked={include[key]}
                  onChange={(e) => setInclude((prev) => ({ ...prev, [key]: e.target.checked }))}
                />
                {label}
                {isRisky && <span className="badge-warn" style={{ marginLeft: 8, fontSize: "0.75rem" }}>Optional / Risky</span>}
              </label>
            );
          })}
        </div>

        {planError && <div className="settings-error">{planError}</div>}
      </section>

      {/* Plan Results */}
      {plan && (
        <section className="settings-section">
          <div className="settings-section-header">
            <div>
              <h2>Cleanup Plan ({plan.total_items} items)</h2>
              <p className="settings-section-desc">
                Review and select items to clean. Only generated cache/DB records are affected.{" "}
                <strong>Original media files will not be deleted.</strong>
              </p>
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <span className="diagnostics-hint">Selected: {fmtBytes(selectedSize)}</span>
              <button className="btn-secondary btn-sm" onClick={toggleAll}>
                {selectedIds.size === plan.items.length ? "Deselect All" : "Select All"}
              </button>
              <button
                className="btn-danger"
                onClick={() => setConfirmOpen(true)}
                disabled={selectedIds.size === 0}
              >
                Clean Selected ({selectedIds.size})
              </button>
            </div>
          </div>

          {plan.total_items === 0 ? (
            <div className="settings-empty">Nothing to clean up. 🎉</div>
          ) : (
            Object.entries(groupedItems(plan.items)).map(([type, items]) => (
              <div key={type} className="cleanup-group">
                <h4 className="cleanup-group-header">
                  {type.replace(/_/g, " ")}
                  <span className="diagnostics-hint" style={{ marginLeft: 8 }}>({items.length})</span>
                </h4>
                <div className="cleanup-items">
                  {items.map((item) => (
                    <label key={item.item_id} className={`cleanup-item ${!item.safe ? "cleanup-item-risky" : ""}`}>
                      <input
                        type="checkbox"
                        checked={selectedIds.has(item.item_id)}
                        onChange={() => toggleItem(item.item_id)}
                      />
                      <div className="cleanup-item-body">
                        <div className="cleanup-item-reason">{item.reason}</div>
                        <div className="cleanup-item-meta">
                          {item.path && <code>{item.path}</code>}
                          {item.size > 0 && <span className="diagnostics-hint">{fmtBytes(item.size)}</span>}
                          {!item.safe && <span className="badge-warn">⚠ Optional</span>}
                        </div>
                      </div>
                    </label>
                  ))}
                </div>
              </div>
            ))
          )}
        </section>
      )}

      {/* Apply Result */}
      {applyResult && (
        <section className="settings-section">
          <div className={`settings-notice ${applyResult.errors.length > 0 ? "settings-error" : ""}`}>
            <strong>Cleanup {applyResult.status}.</strong>{" "}
            Deleted {applyResult.deleted_folders} folder(s), {applyResult.deleted_files} file(s) ({fmtBytes(applyResult.deleted_size)}).
            DB records updated: {applyResult.db_records_updated}.
            {applyResult.errors.length > 0 && (
              <ul>{applyResult.errors.map((e, i) => <li key={i}>{e}</li>)}</ul>
            )}
          </div>
        </section>
      )}

      {/* Confirmation Modal */}
      {confirmOpen && plan && (
        <div className="modal-overlay" onClick={() => !applying && setConfirmOpen(false)}>
          <div className="modal-box" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Confirm Cleanup</h3>
              {!applying && (
                <button className="modal-close" onClick={() => setConfirmOpen(false)}>✕</button>
              )}
            </div>
            <div className="modal-body">
              <p>
                You are about to delete <strong>{selectedIds.size}</strong> item(s) ({fmtBytes(selectedSize)}).
              </p>
              <p className="form-hint" style={{ color: "#22c55e" }}>
                ✓ <strong>Original media files will NOT be deleted.</strong> Only generated HLS cache,
                thumbnails, and stale DB records are affected.
              </p>
              {[...selectedIds].some((id) => plan.items.find((i) => i.item_id === id)?.safe === false) && (
                <p className="form-hint" style={{ color: "#f59e0b" }}>
                  ⚠ Some selected items are marked <em>Optional / Risky</em>. These include HLS cache for
                  source-removed or missing-file videos which may be useful if those sources return.
                </p>
              )}
              {applyError && <div className="settings-error">{applyError}</div>}
            </div>
            <div className="modal-footer">
              <button className="btn-secondary" onClick={() => setConfirmOpen(false)} disabled={applying}>
                Cancel
              </button>
              <button className="btn-danger" onClick={() => void handleApply()} disabled={applying}>
                {applying ? "Cleaning…" : "Clean Selected"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

