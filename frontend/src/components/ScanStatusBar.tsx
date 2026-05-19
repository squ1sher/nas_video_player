import type { ScanStatus } from "../types/video";

type Props = {
  status: ScanStatus | null;
  noSourcesMessage?: string | null;
};

export function ScanStatusBar({ status, noSourcesMessage }: Props) {
  if (noSourcesMessage) {
    return (
      <div className="scan-status scan-no-sources">
        ℹ️ {noSourcesMessage}
      </div>
    );
  }

  if (!status || status.status === "idle") return null;

  const currentFile = status.current_file ? status.current_file.split("/").pop() : null;
  const currentRoot = status.current_root ? status.current_root.split("/").filter(Boolean).pop() ?? status.current_root : null;
  const rootProgress = status.total_roots > 0 ? ` (${status.roots_scanned}/${status.total_roots} roots)` : "";

  if (status.status === "running" || status.status === "cancelling") {
    return (
      <div className="scan-status scan-running">
        <span className="scan-spinner" />
        {status.status === "cancelling" ? "Cancelling scan" : "Scanning library"}
        {rootProgress}
        {currentRoot ? ` — ${currentRoot}` : ""}
        {currentFile ? `: ${currentFile}` : "..."}
      </div>
    );
  }

  if (status.status === "completed") {
    // special case: scan finished but nothing was configured
    if (status.total_roots === 0 && status.message) {
      return (
        <div className="scan-status scan-no-sources">
          ℹ️ {status.message}
        </div>
      );
    }
    return (
      <div className="scan-status scan-done">
        ✓ Scan complete{rootProgress} &mdash; {status.scanned_files} scanned, {status.detected_videos} detected videos,{" "}
        {status.existing_unchanged} unchanged, {status.added} added, {status.updated} updated,{" "}
        {status.removed_missing} removed missing, {status.probe_failed} probe failed
        {status.errors.length > 0 && (
          <span className="scan-errors"> &bull; {status.errors.length} error(s)</span>
        )}
      </div>
    );
  }

  if (status.status === "cancelled") {
    return <div className="scan-status scan-failed">Scan cancelled.</div>;
  }

  if (status.status === "interrupted") {
    return <div className="scan-status scan-failed">Previous scan was interrupted by application restart.</div>;
  }

  if (status.status === "failed") {
    return (
      <div className="scan-status scan-failed">
        ✗ Scan failed
        {status.errors.length > 0 && `: ${status.errors[0]}`}
      </div>
    );
  }

  return null;
}
