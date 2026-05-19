import type {
  DuplicateGroup,
  DuplicateMode,
  DuplicateScanStatus,
  DuplicateSummary,
  FolderInfo,
  HlsGlobalStatus,
  HlsDiagnostics,
  HlsBatchDetail,
  HlsJob,
  HlsLibraryBatchResponse,
  HlsPrepareResponse,
  HlsRepairResponse,
  HlsVideoStatus,
  LibraryRoot,
  LibraryRootIn,
  LibraryRootUpdate,
  LibrarySummary,
  MediaProfileDetail,
  MediaProfileItem,
  ManualPlaybackStatus,
  PathValidationResult,
  PlaybackSource,
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
    const text = await response.text();
    let message = text || `Request failed with status ${response.status}`;
    try {
      const parsed = JSON.parse(text);
      if (typeof parsed?.detail === "string") {
        message = parsed.detail;
      } else if (typeof parsed?.detail?.message === "string") {
        message = parsed.detail.message;
      } else if (typeof parsed?.message === "string") {
        message = parsed.message;
      }
    } catch {
      // keep raw text fallback
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export type SortField = "created_at" | "file_modified_at" | "indexed_at" | "title" | "duration" | "size";
export type SortOrder = "asc" | "desc";

export async function fetchVideos(params: {
  q?: string;
  folder?: string;
  compatibility_status?: string;
  media_status?: string;
  probe_status?: string;
  thumbnail_status?: string;
  extension?: string;
  has_probe_error?: boolean;
  has_thumbnail?: boolean;
  media_profile_id?: number;
  compatibility_source?: string;
  effective_compatibility_status?: string;
  sort?: SortField;
  order?: SortOrder;
}): Promise<VideoListItem[]> {
  const query = new URLSearchParams();
  if (params.q) query.set("q", params.q);
  if (params.folder !== undefined) query.set("folder", params.folder);
  if (params.compatibility_status) query.set("compatibility_status", params.compatibility_status);
  if (params.media_status) query.set("media_status", params.media_status);
  if (params.probe_status) query.set("probe_status", params.probe_status);
  if (params.thumbnail_status) query.set("thumbnail_status", params.thumbnail_status);
  if (params.extension) query.set("extension", params.extension);
  if (params.has_probe_error !== undefined) query.set("has_probe_error", String(params.has_probe_error));
  if (params.has_thumbnail !== undefined) query.set("has_thumbnail", String(params.has_thumbnail));
  if (params.media_profile_id !== undefined) query.set("media_profile_id", String(params.media_profile_id));
  if (params.compatibility_source) query.set("compatibility_source", params.compatibility_source);
  if (params.effective_compatibility_status) query.set("effective_compatibility_status", params.effective_compatibility_status);
  if (params.sort) query.set("sort", params.sort);
  if (params.order) query.set("order", params.order);

  const suffix = query.toString() ? `?${query}` : "";
  return handleResponse<VideoListItem[]>(await fetch(`${API_BASE}/videos${suffix}`));
}

export async function fetchVideo(id: string | number): Promise<VideoDetail> {
  return handleResponse<VideoDetail>(await fetch(`${API_BASE}/videos/${id}`));
}

export async function getPlaybackSource(videoId: number): Promise<PlaybackSource> {
  return handleResponse<PlaybackSource>(await fetch(`${API_BASE}/videos/${videoId}/playback-source?t=${Date.now()}`, { cache: "no-store" }));
}

export async function prepareVideoHls(
  videoId: number,
  body: { force?: boolean; qualities?: string[] } = {},
): Promise<HlsPrepareResponse> {
  return handleResponse<HlsPrepareResponse>(
    await fetch(`${API_BASE}/videos/${videoId}/hls/prepare`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        force: body.force ?? false,
        qualities: body.qualities ?? ["480p", "720p", "1080p"],
      }),
    })
  );
}

export async function getVideoHlsStatus(videoId: number): Promise<HlsVideoStatus> {
  return handleResponse<HlsVideoStatus>(
    await fetch(`${API_BASE}/videos/${videoId}/hls/status?t=${Date.now()}`, { cache: "no-store" })
  );
}

export async function getHlsJobs(): Promise<HlsJob[]> {
  return handleResponse<HlsJob[]>(await fetch(`${API_BASE}/hls/jobs?t=${Date.now()}`, { cache: "no-store" }));
}

export async function getHlsGlobalStatus(): Promise<HlsGlobalStatus> {
  return handleResponse<HlsGlobalStatus>(await fetch(`${API_BASE}/hls/status?t=${Date.now()}`, { cache: "no-store" }));
}

export async function createLibraryHlsBatch(body: {
  qualities?: string[];
  skip_existing?: boolean;
  force?: boolean;
  only_missing_hls?: boolean;
} = {}): Promise<HlsLibraryBatchResponse> {
  return handleResponse<HlsLibraryBatchResponse>(
    await fetch(`${API_BASE}/hls/batches/library`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        qualities: body.qualities ?? ["480p", "720p", "1080p"],
        skip_existing: body.skip_existing ?? true,
        force: body.force ?? false,
        only_missing_hls: body.only_missing_hls ?? true,
      }),
    })
  );
}

export async function getHlsBatch(
  batchId: number,
  opts: { include_items?: boolean; item_status?: string; limit?: number; offset?: number } = {},
): Promise<HlsBatchDetail> {
  const params = new URLSearchParams();
  params.set("include_items", String(opts.include_items ?? false));
  if (opts.item_status) params.set("item_status", opts.item_status);
  if (opts.limit !== undefined) params.set("limit", String(opts.limit));
  if (opts.offset !== undefined) params.set("offset", String(opts.offset));
  params.set("t", String(Date.now()));

  return handleResponse<HlsBatchDetail>(await fetch(`${API_BASE}/hls/batches/${batchId}?${params}`, { cache: "no-store" }));
}

export async function cancelHlsBatch(batchId: number): Promise<HlsBatchDetail> {
  return handleResponse<HlsBatchDetail>(
    await fetch(`${API_BASE}/hls/batches/${batchId}/cancel`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    })
  );
}

export async function repairStaleHls(): Promise<HlsRepairResponse> {
  return handleResponse<HlsRepairResponse>(
    await fetch(`${API_BASE}/hls/repair`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    })
  );
}

export async function getHlsDiagnostics(opts: { details?: boolean; limit?: number; offset?: number } = {}): Promise<HlsDiagnostics> {
  const params = new URLSearchParams();
  params.set("details", String(opts.details ?? false));
  if (opts.limit !== undefined) params.set("limit", String(opts.limit));
  if (opts.offset !== undefined) params.set("offset", String(opts.offset));
  params.set("t", String(Date.now()));
  return handleResponse<HlsDiagnostics>(await fetch(`${API_BASE}/hls/diagnostics?${params}`, { cache: "no-store" }));
}

export async function runScan(): Promise<ScanStartedResponse> {
  return handleResponse<ScanStartedResponse>(
    await fetch(`${API_BASE}/scan`, { method: "POST" })
  );
}

export async function cancelScan(): Promise<ScanStartedResponse> {
  return handleResponse<ScanStartedResponse>(
    await fetch(`${API_BASE}/scan/cancel`, { method: "POST" })
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

export async function getLibrarySummary(): Promise<LibrarySummary> {
  return handleResponse<LibrarySummary>(
    await fetch(`${API_BASE}/library/summary?t=${Date.now()}`, { cache: "no-store" })
  );
}

export async function getMediaProfiles(): Promise<MediaProfileItem[]> {
  return handleResponse<MediaProfileItem[]>(await fetch(`${API_BASE}/media-profiles?t=${Date.now()}`, { cache: "no-store" }));
}

export async function getMediaProfile(profileId: number, limit = 20, offset = 0): Promise<MediaProfileDetail> {
  return handleResponse<MediaProfileDetail>(
    await fetch(`${API_BASE}/media-profiles/${profileId}?limit=${limit}&offset=${offset}&t=${Date.now()}`, { cache: "no-store" })
  );
}

export async function setMediaProfilePlaybackStatus(
  profileId: number,
  manualPlaybackStatus: ManualPlaybackStatus,
  manualPlaybackNote?: string,
): Promise<MediaProfileItem> {
  return handleResponse<MediaProfileItem>(
    await fetch(`${API_BASE}/media-profiles/${profileId}/playback-status`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        manual_playback_status: manualPlaybackStatus,
        manual_playback_note: manualPlaybackNote,
      }),
    })
  );
}

export async function clearMediaProfilePlaybackStatus(profileId: number): Promise<MediaProfileItem> {
  return handleResponse<MediaProfileItem>(
    await fetch(`${API_BASE}/media-profiles/${profileId}/playback-status`, {
      method: "DELETE",
    })
  );
}

export async function startDuplicateScan(): Promise<{ status: string; mode: DuplicateMode }> {
  return handleResponse<{ status: string; mode: DuplicateMode }>(
    await fetch(`${API_BASE}/duplicates/scan`, { method: "POST" })
  );
}

export async function getDuplicateStatus(): Promise<DuplicateScanStatus> {
  return handleResponse<DuplicateScanStatus>(
    await fetch(`${API_BASE}/duplicates/status?t=${Date.now()}`, { cache: "no-store" })
  );
}

export async function getDuplicateGroups(): Promise<DuplicateGroup[]> {
  return handleResponse<DuplicateGroup[]>(
    await fetch(`${API_BASE}/duplicates/groups?t=${Date.now()}`, { cache: "no-store" })
  );
}

export async function getDuplicateSummary(): Promise<DuplicateSummary> {
  return handleResponse<DuplicateSummary>(
    await fetch(`${API_BASE}/duplicates/summary?t=${Date.now()}`, { cache: "no-store" })
  );
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

export async function reprobeVideo(videoId: number): Promise<VideoDetail> {
  return handleResponse<VideoDetail>(
    await fetch(`${API_BASE}/videos/${videoId}/reprobe`, {
      method: "POST",
    })
  );
}

export async function regenerateThumbnail(videoId: number): Promise<VideoDetail> {
  return handleResponse<VideoDetail>(
    await fetch(`${API_BASE}/videos/${videoId}/thumbnail/regenerate`, {
      method: "POST",
    })
  );
}

// ── Settings – Media Sources ───────────────────────────────────────────────

export async function getMediaSources(): Promise<LibraryRoot[]> {
  return handleResponse<LibraryRoot[]>(
    await fetch(`${API_BASE}/settings/media-sources?t=${Date.now()}`, { cache: "no-store" })
  );
}

export async function getMediaSource(id: number): Promise<LibraryRoot> {
  return handleResponse<LibraryRoot>(
    await fetch(`${API_BASE}/settings/media-sources/${id}`)
  );
}

export async function createMediaSource(data: LibraryRootIn): Promise<LibraryRoot> {
  return handleResponse<LibraryRoot>(
    await fetch(`${API_BASE}/settings/media-sources`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    })
  );
}

export async function updateMediaSource(id: number, data: LibraryRootUpdate): Promise<LibraryRoot> {
  return handleResponse<LibraryRoot>(
    await fetch(`${API_BASE}/settings/media-sources/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    })
  );
}

export async function deleteMediaSource(id: number): Promise<{ deleted: boolean; message: string }> {
  return handleResponse<{ deleted: boolean; message: string }>(
    await fetch(`${API_BASE}/settings/media-sources/${id}`, {
      method: "DELETE",
    })
  );
}

export async function validateMediaSourcePath(path: string): Promise<PathValidationResult> {
  return handleResponse<PathValidationResult>(
    await fetch(`${API_BASE}/settings/media-sources/validate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    })
  );
}

export async function scanMediaSource(id: number): Promise<ScanStartedResponse> {
  return handleResponse<ScanStartedResponse>(
    await fetch(`${API_BASE}/settings/media-sources/${id}/scan`, {
      method: "POST",
    })
  );
}
