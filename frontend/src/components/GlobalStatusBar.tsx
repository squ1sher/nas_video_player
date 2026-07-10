import { useEffect, useMemo, useState } from "react";

import {
  cancelHlsBatch,
  cancelPhotoPrepare,
  cancelScan,
  getDuplicateStatus,
  getHlsBatch,
  getHlsGlobalStatus,
  getPhotoPrepareStatus,
  getScanStatus,
} from "../api/client";
import type { DuplicateScanStatus, HlsBatchDetail, HlsGlobalStatus, PhotoPrepareStatus, ScanStatus } from "../types/video";

type ProcessItem = {
  key: string;
  title: string;
  message: string;
  canCancel: boolean;
  cancel?: () => Promise<void>;
};

function isScanActive(scan: ScanStatus | null): boolean {
  return scan?.status === "running" || scan?.status === "cancelling";
}

function isDuplicateActive(status: DuplicateScanStatus | null): boolean {
  return status?.status === "running";
}

function isHlsActive(hls: HlsGlobalStatus | null, batch: HlsBatchDetail | null): boolean {
  if (!hls) return false;
  if (hls.running > 0 || hls.queued_jobs > 0) return true;
  if (!batch) return false;
  return batch.status === "queued" || batch.status === "running";
}

function isPhotoPrepareActive(status: PhotoPrepareStatus | null): boolean {
  return status?.status === "queued" || status?.status === "running";
}

export function GlobalStatusBar() {
  const [scan, setScan] = useState<ScanStatus | null>(null);
  const [duplicate, setDuplicate] = useState<DuplicateScanStatus | null>(null);
  const [hls, setHls] = useState<HlsGlobalStatus | null>(null);
  const [hlsBatch, setHlsBatch] = useState<HlsBatchDetail | null>(null);
  const [photoPrepare, setPhotoPrepare] = useState<PhotoPrepareStatus | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);

  const loadStatuses = async () => {
    try {
      const [scanStatus, duplicateStatus, hlsStatus, photoPrepareStatus] = await Promise.all([
        getScanStatus(),
        getDuplicateStatus(),
        getHlsGlobalStatus(),
        getPhotoPrepareStatus(),
      ]);
      setScan(scanStatus);
      setDuplicate(duplicateStatus);
      setHls(hlsStatus);
      setPhotoPrepare(photoPrepareStatus);

      if (hlsStatus.active_batch_id !== null) {
        const batch = await getHlsBatch(hlsStatus.active_batch_id, { include_items: false });
        setHlsBatch(batch);
      } else {
        setHlsBatch(null);
      }
    } catch {
      // Keep the status bar silent on polling errors.
    }
  };

  useEffect(() => {
    void loadStatuses();
  }, []);

  useEffect(() => {
    const active = isScanActive(scan) || isDuplicateActive(duplicate) || isHlsActive(hls, hlsBatch) || isPhotoPrepareActive(photoPrepare);
    const ms = active ? 2500 : 10000;
    const id = setInterval(() => {
      void loadStatuses();
    }, ms);
    return () => clearInterval(id);
  }, [scan, duplicate, hls, hlsBatch, photoPrepare]);

  const items = useMemo<ProcessItem[]>(() => {
    const next: ProcessItem[] = [];

    if (isScanActive(scan)) {
      const currentName = scan?.current_file ? scan.current_file.split("/").pop() : null;
      next.push({
        key: "scan",
        title: "Scanning library",
        message: `${scan?.scanned_files ?? 0} files${currentName ? ` · current: ${currentName}` : ""}${
          scan && scan.errors.length > 0 ? ` · errors: ${scan.errors.length}` : ""
        }`,
        canCancel: true,
        cancel: async () => {
          await cancelScan();
          await loadStatuses();
        },
      });
    }

    if (isHlsActive(hls, hlsBatch)) {
      const progress = hlsBatch ? `${Math.round(hlsBatch.progress_percent)}%` : "running";
      const current = hlsBatch?.current_video?.title;
      next.push({
        key: "hls",
        title: "Preparing HLS",
        message: `${progress}${current ? ` · current: ${current}` : ""}${
          hls ? ` · jobs ${hls.running}/${hls.max_concurrent}, queued ${hls.queued_jobs}` : ""
        }`,
        canCancel: Boolean(hlsBatch && (hlsBatch.status === "queued" || hlsBatch.status === "running")),
        cancel: hlsBatch
          ? async () => {
              await cancelHlsBatch(hlsBatch.id);
              await loadStatuses();
            }
          : undefined,
      });
    }

    if (isPhotoPrepareActive(photoPrepare)) {
      const currentName = photoPrepare?.current_path ? photoPrepare.current_path.split("/").pop() : null;
      next.push({
        key: "photo-prepare",
        title: "Preparing photos",
        message: `${photoPrepare?.processed ?? 0} / ${photoPrepare?.total ?? 0}${currentName ? ` · ${currentName}` : ""}${
          photoPrepare && photoPrepare.failed > 0 ? ` · failed ${photoPrepare.failed}` : ""
        }`,
        canCancel: true,
        cancel: async () => {
          await cancelPhotoPrepare();
          await loadStatuses();
        },
      });
    }

    if (isDuplicateActive(duplicate)) {
      next.push({
        key: "duplicates",
        title: "Scanning duplicates",
        message: `${duplicate?.videos_checked ?? 0} checked${
          duplicate?.current_step ? ` · ${duplicate.current_step}` : ""
        }`,
        canCancel: false,
      });
    }

    return next;
  }, [scan, duplicate, hls, hlsBatch, photoPrepare]);

  if (items.length === 0) return null;

  return (
    <div className="global-status-bar" role="status" aria-live="polite">
      <div className="global-status-inner">
        {items.map((item) => (
          <div className="global-status-item" key={item.key}>
            <strong>{item.title}</strong>
            <span>{item.message}</span>
            {item.canCancel && item.cancel && (
              <button
                className="btn-secondary btn-sm"
                disabled={busyKey === item.key}
                onClick={async () => {
                  try {
                    setBusyKey(item.key);
                    await item.cancel?.();
                  } finally {
                    setBusyKey(null);
                  }
                }}
              >
                {busyKey === item.key ? "Cancelling..." : "Cancel"}
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

