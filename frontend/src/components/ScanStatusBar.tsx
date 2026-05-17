import type { ScanStatus } from "../types/video";

type Props = {
  status: ScanStatus | null;
};

export function ScanStatusBar({ status }: Props) {
  if (!status || status.status === "idle") return null;

  if (status.status === "running" || status.status === "cancelling") {
    return (
      <div className="scan-status scan-running">
        <span className="scan-spinner" />
        {status.status === "cancelling" ? "Cancelling scan" : "Scanning library"}
        {status.current_file ? `: ${status.current_file.split("/").pop()}` : "..."}
      </div>
    );
  }

  if (status.status === "completed") {
    return (
      <div className="scan-status scan-done">
        ✓ Scan complete &mdash; {status.scanned_files} scanned, {status.detected_videos} detected videos,{" "}
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
