import type {
  FolderInfo,
  ScanStartedResponse,
  ScanStatus,
  VideoDetail,
  VideoListItem,
  VideoWithProgress,
  WatchProgress,
} from "../types/video";

const API_BASE = "/api";

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Request failed with status ${response.status}`);
  }
  return (await response.json()) as T;
}

export type SortField = "created_at" | "file_modified_at" | "indexed_at" | "title" | "duration" | "size";
export type SortOrder = "asc" | "desc";

export async function fetchVideos(params: {
  q?: string;
  folder?: string;
  sort?: SortField;
  order?: SortOrder;
}): Promise<VideoListItem[]> {
  const query = new URLSearchParams();
  if (params.q) query.set("q", params.q);
  if (params.folder !== undefined) query.set("folder", params.folder);
  if (params.sort) query.set("sort", params.sort);
  if (params.order) query.set("order", params.order);

  const suffix = query.toString() ? `?${query}` : "";
  return handleResponse<VideoListItem[]>(await fetch(`${API_BASE}/videos${suffix}`));
}

export async function fetchVideo(id: string | number): Promise<VideoDetail> {
  return handleResponse<VideoDetail>(await fetch(`${API_BASE}/videos/${id}`));
}

export async function runScan(): Promise<ScanStartedResponse> {
  return handleResponse<ScanStartedResponse>(
    await fetch(`${API_BASE}/scan`, { method: "POST" })
  );
}

export async function getScanStatus(): Promise<ScanStatus> {
  return handleResponse<ScanStatus>(
    await fetch(`${API_BASE}/scan/status?t=${Date.now()}`, { cache: "no-store" })
  );
}

export async function getLastScanResult(): Promise<ScanStatus> {
  return handleResponse<ScanStatus>(
    await fetch(`${API_BASE}/scan/last-result?t=${Date.now()}`, { cache: "no-store" })
  );
}

export async function getProgress(videoId: number): Promise<WatchProgress> {
  return handleResponse<WatchProgress>(await fetch(`${API_BASE}/videos/${videoId}/progress`));
}

export async function updateProgress(
  videoId: number,
  positionSeconds: number,
  durationSeconds: number,
  keepalive = false,
): Promise<WatchProgress> {
  return handleResponse<WatchProgress>(
    await fetch(`${API_BASE}/videos/${videoId}/progress`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ position_seconds: positionSeconds, duration_seconds: durationSeconds }),
      keepalive,
    })
  );
}

export async function getContinueWatching(): Promise<VideoWithProgress[]> {
  return handleResponse<VideoWithProgress[]>(await fetch(`${API_BASE}/videos/continue-watching`));
}

export async function getFolders(): Promise<FolderInfo[]> {
  return handleResponse<FolderInfo[]>(await fetch(`${API_BASE}/folders`));
}

export function getDownloadUrl(videoId: number): string {
  return `${API_BASE}/videos/${videoId}/download`;
}

export async function deleteVideo(videoId: number): Promise<{ deleted: boolean }> {
  return handleResponse<{ deleted: boolean }>(
    await fetch(`${API_BASE}/videos/${videoId}`, {
      method: "DELETE",
    })
  );
}

