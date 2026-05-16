import type { ScanStatus } from "../types/video";

type Props = {
  status: ScanStatus | null;
};

export function ScanStatusBar({ status }: Props) {
  if (!status || status.status === "idle") return null;

  if (status.status === "running") {
    return (
      <div className="scan-status scan-running">
        <span className="scan-spinner" />
        Scanning library
        {status.current_file ? `: ${status.current_file.split("/").pop()}` : "..."}
      </div>
    );
  }

  if (status.status === "completed") {
    return (
      <div className="scan-status scan-done">
        ✓ Scan complete &mdash; {status.scanned_files} scanned, {status.detected_videos} detected videos,{" "}
        {status.added} added, {status.updated} updated, {status.probe_failed} probe failed
        {status.errors.length > 0 && (
          <span className="scan-errors"> &bull; {status.errors.length} error(s)</span>
        )}
      </div>
    );
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
