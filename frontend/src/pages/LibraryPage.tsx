import { useEffect, useMemo, useRef, useState } from "react";
import {
  cancelScan,
  cancelHlsBatch,
  clearMediaProfilePlaybackStatus,
  createLibraryHlsBatch,
  deleteVideo,
  fetchVideos,
  getContinueWatching,
  getDuplicateGroups,
  getHlsDiagnostics,
  getMediaProfiles,
  repairStaleHls,
  getHlsBatch,
  getHlsGlobalStatus,
  getLibrarySummary,
  getDuplicateStatus,
  getDuplicateSummary,
  getScanStatus,
  runScan,
  setMediaProfilePlaybackStatus,
  startDuplicateScan,
} from "../api/client";
import type { SortField, SortOrder } from "../api/client";
import { ScanStatusBar } from "../components/ScanStatusBar";
import { SearchBar } from "../components/SearchBar";
import { SortSelect } from "../components/SortSelect";
import { VideoCard } from "../components/VideoCard";
import { FolderTree } from "../components/folders/FolderTree";
import type {
  DuplicateGroup,
  DuplicateScanStatus,
  DuplicateSummary,
  HlsBatchDetail,
  HlsDiagnostics,
  HlsGlobalStatus,
  LibrarySummary,
  ManualPlaybackStatus,
  MediaProfileItem,
  ScanStatus,
  VideoListItem,
  VideoWithProgress,
} from "../types/video";
import { buildFolderTree } from "../utils/buildFolderTree";
import { groupVideos } from "../utils/groupVideos";

type Tab = "all" | "folders" | "continue" | "recent" | "duplicates" | "diagnostics";
type ProfileSort = "default" | "files_count_desc" | "extension" | "effective_status";

function formatDuration(seconds: number | null): string {
  if (!seconds) return "Unknown";
  const total = Math.floor(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h > 0
    ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
    : `${m}:${String(s).padStart(2, "0")}`;
}

function formatBytes(bytes: number): string {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function confidenceLabel(confidence: DuplicateGroup["confidence"]): string {
  if (confidence === "exact_metadata_match") return "Exact metadata match";
  if (confidence === "high") return "High confidence";
  return "Medium confidence";
}

export function LibraryPage() {
  const [tab, setTab] = useState<Tab>("all");
  const [videos, setVideos] = useState<VideoListItem[]>([]);
  const [continueWatching, setContinueWatching] = useState<VideoWithProgress[]>([]);
  const [folderVideos, setFolderVideos] = useState<VideoListItem[]>([]);
  const [folderLoading, setFolderLoading] = useState(true);
  const [scanStatus, setScanStatus] = useState<ScanStatus | null>(null);
  const [duplicateStatus, setDuplicateStatus] = useState<DuplicateScanStatus | null>(null);
  const [duplicateSummary, setDuplicateSummary] = useState<DuplicateSummary | null>(null);
  const [librarySummary, setLibrarySummary] = useState<LibrarySummary | null>(null);
  const [duplicateGroups, setDuplicateGroups] = useState<DuplicateGroup[]>([]);
  const duplicateMode = "strict";
  const [deletingVideoId, setDeletingVideoId] = useState<number | null>(null);
  const [selectedDuplicateIds, setSelectedDuplicateIds] = useState<Set<number>>(new Set());
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [bulkDeleteProgress, setBulkDeleteProgress] = useState<{ done: number; total: number } | null>(null);
  const [loading, setLoading] = useState(true);
  const [duplicateLoading, setDuplicateLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [duplicateError, setDuplicateError] = useState<string | null>(null);
  const [hlsGlobal, setHlsGlobal] = useState<HlsGlobalStatus | null>(null);
  const [activeHlsBatch, setActiveHlsBatch] = useState<HlsBatchDetail | null>(null);
  const [hlsBatchBusy, setHlsBatchBusy] = useState(false);
  const [hlsCancelBusy, setHlsCancelBusy] = useState(false);
  const [hlsRepairBusy, setHlsRepairBusy] = useState(false);
  const [hlsMaintenanceMessage, setHlsMaintenanceMessage] = useState<string | null>(null);
  const [hlsDiagnostics, setHlsDiagnostics] = useState<HlsDiagnostics | null>(null);
  const [showHlsLibraryConfirm, setShowHlsLibraryConfirm] = useState(false);
  const [hlsSkipExisting, setHlsSkipExisting] = useState(true);
  const [hlsForceRegenerate, setHlsForceRegenerate] = useState(false);
  const [search, setSearch] = useState("");
  const [playbackFilter, setPlaybackFilter] = useState<string>("all");
  const [mediaStatusFilter, setMediaStatusFilter] = useState<string | undefined>(undefined);
  const [probeStatusFilter, setProbeStatusFilter] = useState<string | undefined>(undefined);
  const [thumbnailStatusFilter, setThumbnailStatusFilter] = useState<string | undefined>(undefined);
  const [extensionFilter, setExtensionFilter] = useState<string | undefined>(undefined);
  const [hasProbeErrorFilter, setHasProbeErrorFilter] = useState<boolean | undefined>(undefined);
  const [hasThumbnailFilter, setHasThumbnailFilter] = useState<boolean | undefined>(undefined);
  const [sort, setSort] = useState<SortField>("file_modified_at");
  const [order, setOrder] = useState<SortOrder>("desc");
  const [probeFailedFiles, setProbeFailedFiles] = useState<VideoListItem[]>([]);
  const [needsConversionFiles, setNeedsConversionFiles] = useState<VideoListItem[]>([]);
  const [unknownCompatibilityFiles, setUnknownCompatibilityFiles] = useState<VideoListItem[]>([]);
  const [thumbnailFailedFiles, setThumbnailFailedFiles] = useState<VideoListItem[]>([]);
  const [mediaProfiles, setMediaProfiles] = useState<MediaProfileItem[]>([]);
  const [profileEffectiveFilter, setProfileEffectiveFilter] = useState<string>("all");
  const [profileOnlyMissingManual, setProfileOnlyMissingManual] = useState(true);
  const [profileExtensionFilter, setProfileExtensionFilter] = useState<string>("");
  const [profileSort, setProfileSort] = useState<ProfileSort>("default");
  const [profileActionBusyId, setProfileActionBusyId] = useState<number | null>(null);
  const [collapsedVideoGroups, setCollapsedVideoGroups] = useState<Set<string>>(new Set());
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set());
  const libraryPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const duplicatePollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const liveRefreshInFlightRef = useRef(false);
  const lastLiveRefreshAtRef = useRef(0);

  const folderTree = useMemo(() => buildFolderTree(folderVideos), [folderVideos]);
  const groupedVideos = useMemo(() => groupVideos(videos, { sort, order }), [videos, sort, order]);
  const progressMap = Object.fromEntries(continueWatching.map((video) => [video.id, video.progress]));
  const duplicateVideoMap = useMemo(() => {
    const map = new Map<number, DuplicateGroup["videos"][number]>();
    for (const group of duplicateGroups) {
      for (const video of group.videos) {
        map.set(video.id, video);
      }
    }
    return map;
  }, [duplicateGroups]);
  const selectedDuplicateVideos = useMemo(
    () =>
      [...selectedDuplicateIds]
        .map((id) => duplicateVideoMap.get(id))
        .filter((video): video is DuplicateGroup["videos"][number] => video !== undefined),
    [selectedDuplicateIds, duplicateVideoMap]
  );
  const selectedDuplicateTotalSize = useMemo(
    () => selectedDuplicateVideos.reduce((acc, video) => acc + video.size, 0),
    [selectedDuplicateVideos]
  );
  const filteredMediaProfiles = useMemo(() => {
    let rows = [...mediaProfiles];
    if (profileEffectiveFilter !== "all") {
      rows = rows.filter((profile) => profile.effective_compatibility_status === profileEffectiveFilter);
    }
    if (profileOnlyMissingManual) {
      rows = rows.filter((profile) => profile.manual_playback_status === null);
    }
    if (profileExtensionFilter.trim()) {
      const ext = profileExtensionFilter.trim().toLowerCase();
      const normalized = ext.startsWith(".") ? ext : `.${ext}`;
      rows = rows.filter((profile) => profile.extension === normalized);
    }

    if (profileSort === "files_count_desc") {
      rows.sort((a, b) => b.files_count - a.files_count);
    } else if (profileSort === "extension") {
      rows.sort((a, b) => a.extension.localeCompare(b.extension));
    } else if (profileSort === "effective_status") {
      rows.sort((a, b) => a.effective_compatibility_status.localeCompare(b.effective_compatibility_status));
    } else {
      rows.sort((a, b) => {
        const aMissing = a.manual_playback_status === null ? 0 : 1;
        const bMissing = b.manual_playback_status === null ? 0 : 1;
        if (aMissing !== bMissing) return aMissing - bMissing;
        return b.files_count - a.files_count;
      });
    }
    return rows;
  }, [mediaProfiles, profileEffectiveFilter, profileOnlyMissingManual, profileExtensionFilter, profileSort]);

  const applyOptimisticProfileStatus = (profileId: number, manualStatus: ManualPlaybackStatus | null) => {
    setMediaProfiles((prev) =>
      prev.map((profile) => {
        if (profile.id !== profileId) return profile;

        const effectiveStatus = manualStatus
          ? manualStatus === "playable"
            ? "direct_play"
            : manualStatus === "not_playable"
              ? "needs_conversion"
              : manualStatus === "partially_playable"
                ? "may_play"
                : "unknown"
          : profile.auto_compatibility_status;

        return {
          ...profile,
          manual_playback_status: manualStatus,
          manual_playback_note: manualStatus ? profile.manual_playback_note : null,
          manual_checked_at: manualStatus ? new Date().toISOString() : null,
          effective_compatibility_status: effectiveStatus,
          compatibility_source: manualStatus ? "manual_profile_override" : "auto_heuristic",
        };
      })
    );
  };

  const stopLibraryPolling = () => {
    if (libraryPollRef.current) {
      clearInterval(libraryPollRef.current);
      libraryPollRef.current = null;
    }
  };

  const stopDuplicatePolling = () => {
    if (duplicatePollRef.current) {
      clearInterval(duplicatePollRef.current);
      duplicatePollRef.current = null;
    }
  };

  const isScanActive = (status: ScanStatus | null): boolean =>
    status?.status === "running" || status?.status === "cancelling";

  const buildVideoQuery = () => {
    const q = search.trim() || undefined;
    const compatibility_status = playbackFilter !== "all" ? playbackFilter : undefined;
    return {
      q,
      compatibility_status,
      media_status: mediaStatusFilter,
      probe_status: probeStatusFilter,
      thumbnail_status: thumbnailStatusFilter,
      extension: extensionFilter,
      has_probe_error: hasProbeErrorFilter,
      has_thumbnail: hasThumbnailFilter,
      sort,
      order,
    };
  };

  const refreshLibraryListsDuringScan = async () => {
    if (liveRefreshInFlightRef.current) return;
    liveRefreshInFlightRef.current = true;
    try {
      const [nextVideos, nextFolderVideos] = await Promise.all([
        fetchVideos(buildVideoQuery()),
        fetchVideos({ sort, order }),
      ]);
      setVideos(nextVideos);
      setFolderVideos(nextFolderVideos);
    } catch {
      // keep existing rendered data; scan status polling continues separately
    } finally {
      liveRefreshInFlightRef.current = false;
    }
  };

  const loadVideos = async () => {
    try {
      setLoading(true);
      setError(null);
      setVideos(await fetchVideos(buildVideoQuery()));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load videos");
    } finally {
      setLoading(false);
    }
  };

  const loadLibrarySummary = async () => {
    try {
      setLibrarySummary(await getLibrarySummary());
    } catch {
      // non-critical
    }
  };

  const loadDiagnosticsSections = async () => {
    try {
      const [probeFailed, needsConversion, unknownCompatibility, thumbnailFailed] = await Promise.all([
        fetchVideos({ probe_status: "failed", sort: "indexed_at", order: "desc" }),
        fetchVideos({ compatibility_status: "needs_conversion", sort: "indexed_at", order: "desc" }),
        fetchVideos({ compatibility_status: "unknown", sort: "indexed_at", order: "desc" }),
        fetchVideos({ thumbnail_status: "failed", sort: "indexed_at", order: "desc" }),
      ]);
      setProbeFailedFiles(probeFailed.slice(0, 20));
      setNeedsConversionFiles(needsConversion.slice(0, 20));
      setUnknownCompatibilityFiles(unknownCompatibility.slice(0, 20));
      setThumbnailFailedFiles(thumbnailFailed.slice(0, 20));
    } catch {
      // non-critical
    }
  };

  const loadMediaProfilesData = async () => {
    try {
      setMediaProfiles(await getMediaProfiles());
    } catch {
      // non-critical
    }
  };

  const loadContinueWatching = async () => {
    try {
      setContinueWatching(await getContinueWatching());
    } catch {
      // non-critical
    }
  };

  const loadFolderVideos = async () => {
    try {
      setFolderLoading(true);
      setFolderVideos(
        await fetchVideos({
          sort,
          order,
        })
      );
    } catch {
      // non-critical
    } finally {
      setFolderLoading(false);
    }
  };

  const loadDuplicateData = async () => {
    try {
      setDuplicateLoading(true);
      setDuplicateError(null);
      const [status, summary, groups] = await Promise.all([
        getDuplicateStatus(),
        getDuplicateSummary(),
        getDuplicateGroups(),
      ]);
      setDuplicateStatus(status);
      setDuplicateSummary(summary);
      setDuplicateGroups(groups);
      if (status.status === "running") {
        startDuplicatePolling();
      }
    } catch (err) {
      setDuplicateError(err instanceof Error ? err.message : "Failed to load duplicate data");
    } finally {
      setDuplicateLoading(false);
    }
  };

  const loadHlsState = async () => {
    try {
      const status = await getHlsGlobalStatus();
      setHlsGlobal(status);
      if (status.active_batch_id) {
        const batch = await getHlsBatch(status.active_batch_id, { include_items: false });
        setActiveHlsBatch(batch);
      } else {
        setActiveHlsBatch(null);
      }
    } catch {
      // non-critical
    }
  };

  const loadHlsDiagnostics = async () => {
    try {
      const payload = await getHlsDiagnostics({ details: false });
      setHlsDiagnostics(payload);
    } catch {
      // non-critical
    }
  };

  const startLibraryPolling = () => {
    if (libraryPollRef.current) return;
    libraryPollRef.current = setInterval(async () => {
      try {
        const status = await getScanStatus();
        setScanStatus(status);

        if (isScanActive(status)) {
          const now = Date.now();
          if (now - lastLiveRefreshAtRef.current >= 6000) {
            lastLiveRefreshAtRef.current = now;
            await refreshLibraryListsDuringScan();
          }
        } else {
          stopLibraryPolling();
          if (status.status === "completed") {
              await Promise.all([
                loadVideos(),
                loadContinueWatching(),
                loadFolderVideos(),
                loadLibrarySummary(),
                loadDiagnosticsSections(),
                loadMediaProfilesData(),
              ]);
          }
        }
      } catch {
        stopLibraryPolling();
      }
    }, 1200);
  };

  const startDuplicatePolling = () => {
    if (duplicatePollRef.current) return;
    duplicatePollRef.current = setInterval(async () => {
      try {
        const status = await getDuplicateStatus();
        setDuplicateStatus(status);
        if (status.status !== "running") {
          stopDuplicatePolling();
          await loadDuplicateData();
        }
      } catch {
        stopDuplicatePolling();
      }
    }, 1200);
  };

  useEffect(() => {
    void loadVideos();
  }, [
    search,
    playbackFilter,
    mediaStatusFilter,
    probeStatusFilter,
    thumbnailStatusFilter,
    extensionFilter,
    hasProbeErrorFilter,
    hasThumbnailFilter,
    sort,
    order,
  ]);

  useEffect(() => {
    void loadContinueWatching();
    void loadFolderVideos();
    void loadLibrarySummary();
    void loadDiagnosticsSections();
    void loadMediaProfilesData();
    void loadHlsState();
    void loadHlsDiagnostics();
    getScanStatus()
      .then((status) => {
        setScanStatus(status);
        if (isScanActive(status)) {
          void refreshLibraryListsDuringScan();
          startLibraryPolling();
        }
      })
      .catch(() => {});
    return () => stopLibraryPolling();
  }, []);

  useEffect(() => {
    if (!activeHlsBatch) return;
    if (!["queued", "running"].includes(activeHlsBatch.status)) return;

    const timer = setInterval(() => {
      void loadHlsState();
    }, 3000);

    return () => clearInterval(timer);
  }, [activeHlsBatch?.id, activeHlsBatch?.status]);

  useEffect(() => {
    void loadFolderVideos();
  }, [sort, order]);

  useEffect(() => {
    void loadDuplicateData();
    return () => stopDuplicatePolling();
  }, []);

  useEffect(() => {
    if (tab === "diagnostics") {
      void Promise.all([loadLibrarySummary(), loadDiagnosticsSections(), loadMediaProfilesData(), loadHlsDiagnostics()]);
    }
  }, [tab]);

  const onSetProfileStatus = async (profileId: number, status: ManualPlaybackStatus) => {
    try {
      setProfileActionBusyId(profileId);
      setError(null);
      applyOptimisticProfileStatus(profileId, status);
      await setMediaProfilePlaybackStatus(profileId, status);
      await Promise.all([loadMediaProfilesData(), loadLibrarySummary(), loadDiagnosticsSections(), loadVideos()]);
    } catch (err) {
      await loadMediaProfilesData();
      setError(err instanceof Error ? err.message : "Failed to update profile status");
    } finally {
      setProfileActionBusyId(null);
    }
  };

  const onClearProfileStatus = async (profileId: number) => {
    try {
      setProfileActionBusyId(profileId);
      setError(null);
      applyOptimisticProfileStatus(profileId, null);
      await clearMediaProfilePlaybackStatus(profileId);
      await Promise.all([loadMediaProfilesData(), loadLibrarySummary(), loadDiagnosticsSections(), loadVideos()]);
    } catch (err) {
      await loadMediaProfilesData();
      setError(err instanceof Error ? err.message : "Failed to clear profile status");
    } finally {
      setProfileActionBusyId(null);
    }
  };

  useEffect(() => {
    // Keep selected IDs in sync with currently visible duplicate results.
    setSelectedDuplicateIds((prev) => {
      const next = new Set<number>();
      prev.forEach((id) => {
        if (duplicateVideoMap.has(id)) next.add(id);
      });
      return next;
    });
  }, [duplicateVideoMap]);

  const handleSortChange = (newSort: SortField, newOrder: SortOrder) => {
    setSort(newSort);
    setOrder(newOrder);
  };

  const handleShowAll = () => {
    setPlaybackFilter("all");
    setMediaStatusFilter(undefined);
    setProbeStatusFilter(undefined);
    setThumbnailStatusFilter(undefined);
    setExtensionFilter(undefined);
    setHasProbeErrorFilter(undefined);
    setHasThumbnailFilter(undefined);
    setTab("all");
  };

  const toggleVideoGroup = (groupKey: string) => {
    setCollapsedVideoGroups((prev) => {
      const next = new Set(prev);
      if (next.has(groupKey)) next.delete(groupKey);
      else next.add(groupKey);
      return next;
    });
  };

  const applyCompatibilityFilter = (status: string) => {
    setPlaybackFilter(status);
    setMediaStatusFilter(undefined);
    setProbeStatusFilter(undefined);
    setThumbnailStatusFilter(undefined);
    setExtensionFilter(undefined);
    setHasProbeErrorFilter(undefined);
    setHasThumbnailFilter(undefined);
    setTab("all");
  };

  const applyDiagnosticFilter = (filters: {
    compatibility_status?: string;
    media_status?: string;
    probe_status?: string;
    thumbnail_status?: string;
    extension?: string;
    has_probe_error?: boolean;
    has_thumbnail?: boolean;
  }) => {
    setPlaybackFilter(filters.compatibility_status ?? "all");
    setMediaStatusFilter(filters.media_status);
    setProbeStatusFilter(filters.probe_status);
    setThumbnailStatusFilter(filters.thumbnail_status);
    setExtensionFilter(filters.extension);
    setHasProbeErrorFilter(filters.has_probe_error);
    setHasThumbnailFilter(filters.has_thumbnail);
    setTab("all");
  };

  const toggleFolder = (path: string) => {
    setExpandedFolders((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  const onScanClick = async () => {
    if (isScanActive(scanStatus)) {
      setError("Library scan is already running.");
      return;
    }

    try {
      setError(null);
      await runScan();
      const status = await getScanStatus();
      setScanStatus(status);
      if (isScanActive(status)) {
        await refreshLibraryListsDuringScan();
        startLibraryPolling();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Scan failed");
    }
  };

  const onCancelScanClick = async () => {
    const confirmed = window.confirm(
      "Cancel library scan?\n\nThe current scan will stop after the current file. No original files will be modified. Missing-file cleanup will not run for a cancelled scan."
    );
    if (!confirmed) return;

    try {
      setError(null);
      const response = await cancelScan();
      if (response.status === "cancelling") {
        setScanStatus(await getScanStatus());
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to cancel scan");
    }
  };

  const onDuplicateScanClick = async () => {
    try {
      setDuplicateError(null);
      await startDuplicateScan();
      const status = await getDuplicateStatus();
      setDuplicateStatus(status);
      startDuplicatePolling();
    } catch (err) {
      setDuplicateError(err instanceof Error ? err.message : "Duplicate scan failed");
    }
  };

  const onDeleteDuplicateVideoClick = async (videoId: number) => {
    const ok = window.confirm("Delete this video from the library and source folder?");
    if (!ok) return;

    try {
      setDuplicateError(null);
      setDeletingVideoId(videoId);
      await deleteVideo(videoId);
      await Promise.all([loadDuplicateData(), loadVideos(), loadContinueWatching(), loadFolderVideos()]);
    } catch (err) {
      setDuplicateError(err instanceof Error ? err.message : "Failed to delete video");
    } finally {
      setDeletingVideoId(null);
    }
  };

  const toggleDuplicateSelection = (videoId: number) => {
    setSelectedDuplicateIds((prev) => {
      const next = new Set(prev);
      if (next.has(videoId)) next.delete(videoId);
      else next.add(videoId);
      return next;
    });
  };

  const onConfirmDeleteSelected = async () => {
    if (selectedDuplicateVideos.length === 0) return;
    try {
      setDeletingVideoId(-1);
      setBulkDeleteProgress({ done: 0, total: selectedDuplicateVideos.length });
      const failures: string[] = [];
      for (const [index, video] of selectedDuplicateVideos.entries()) {
        try {
          await deleteVideo(video.id);
        } catch {
          failures.push(video.relative_path);
        }
        setBulkDeleteProgress({ done: index + 1, total: selectedDuplicateVideos.length });
      }
      await Promise.all([loadDuplicateData(), loadVideos(), loadContinueWatching(), loadFolderVideos()]);
      setSelectedDuplicateIds(new Set());
      setShowDeleteConfirm(false);
      if (failures.length > 0) {
        setDuplicateError(`Failed to delete ${failures.length} file(s): ${failures.slice(0, 5).join(", ")}`);
      }
    } finally {
      setDeletingVideoId(null);
      setBulkDeleteProgress(null);
    }
  };

  const onStartLibraryHlsBatch = async () => {
    try {
      setHlsBatchBusy(true);
      setError(null);
      setHlsMaintenanceMessage(null);
      const result = await createLibraryHlsBatch({
        qualities: ["480p", "720p", "1080p"],
        skip_existing: hlsForceRegenerate ? false : hlsSkipExisting,
        force: hlsForceRegenerate,
        only_missing_hls: true,
      });
      setShowHlsLibraryConfirm(false);
      setError(result.status === "nothing_to_do" ? result.message : null);
      await Promise.all([loadHlsState(), loadHlsDiagnostics()]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start library HLS batch");
    } finally {
      setHlsBatchBusy(false);
    }
  };

  const onCancelLibraryHlsBatch = async () => {
    if (!activeHlsBatch) return;
    const ok = window.confirm("Stop active HLS batch? Current file may finish, queued files will be cancelled.");
    if (!ok) return;

    try {
      setHlsCancelBusy(true);
      setError(null);
      await cancelHlsBatch(activeHlsBatch.id);
      await Promise.all([loadHlsState(), loadHlsDiagnostics()]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to cancel HLS batch");
    } finally {
      setHlsCancelBusy(false);
    }
  };

  const onRepairStaleHls = async () => {
    const ok = window.confirm("Run HLS diagnostics repair now? This only resets stale DB flags where HLS files are missing.");
    if (!ok) return;

    try {
      setHlsRepairBusy(true);
      setError(null);
      const result = await repairStaleHls();
      setHlsMaintenanceMessage(
        `Repair complete: checked ${result.checked}, valid ${result.valid_hls}, missing ${result.missing_hls}, ` +
        `repaired ${result.db_repaired_to_completed}, invalidated ${result.stale_completed_invalidated}.`
      );
      await Promise.all([loadHlsState(), loadHlsDiagnostics()]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to repair stale HLS flags");
    } finally {
      setHlsRepairBusy(false);
    }
  };

  return (
    <div className="page">
      <div className="library-sticky-shell">
        <header className="page-header page-header-actions">
          <h1>NAS Video Player</h1>
          <div className="header-actions">
            <button onClick={onScanClick}>
              {scanStatus?.status === "running" || scanStatus?.status === "cancelling" ? "Scanning…" : "Scan Library"}
            </button>
            {(scanStatus?.status === "running" || scanStatus?.status === "cancelling") && (
              <button className="btn-secondary" onClick={onCancelScanClick}>
                Cancel scan
              </button>
            )}
            <div className="duplicate-actions">
              <button onClick={onDuplicateScanClick} disabled={duplicateStatus?.status === "running"}>
                {duplicateStatus?.status === "running" ? "Scanning duplicates…" : "Scan Duplicates"}
              </button>
              <button onClick={() => setShowHlsLibraryConfirm(true)} disabled={hlsBatchBusy}>
                {hlsBatchBusy ? "Starting HLS batch..." : "Prepare HLS for all missing"}
              </button>
              <button onClick={onRepairStaleHls} disabled={hlsRepairBusy}>
                {hlsRepairBusy ? "Repairing HLS flags..." : "Repair stale HLS flags"}
              </button>
            </div>
          </div>
        </header>

        <ScanStatusBar status={scanStatus} />
        {isScanActive(scanStatus) && <div className="library-updating-badge">Library is updating...</div>}
        {error && <div className="error">{error}</div>}
        {hlsMaintenanceMessage && <div className="notice">{hlsMaintenanceMessage}</div>}
        {duplicateError && <div className="error">{duplicateError}</div>}
        {activeHlsBatch && (
          <div className="notice">
            <strong>Overnight HLS batch #{activeHlsBatch.id}</strong>
            {" - "}{activeHlsBatch.status}
            {" - "}{Math.round(activeHlsBatch.progress_percent)}%
            {" - completed "}{activeHlsBatch.completed_count}/{activeHlsBatch.total_count}
            {", queued "}{activeHlsBatch.queued_count}
            {", failed "}{activeHlsBatch.failed_count}
            {", skipped "}{activeHlsBatch.skipped_count}
            {hlsGlobal ? `, running jobs ${hlsGlobal.running}/${hlsGlobal.max_concurrent}, queued jobs ${hlsGlobal.queued_jobs}` : ""}
            {activeHlsBatch.current_video ? ` - current: ${activeHlsBatch.current_video.title}` : ""}
            {["queued", "running"].includes(activeHlsBatch.status) && (
              <button
                className="btn-danger"
                style={{ marginLeft: 8 }}
                onClick={onCancelLibraryHlsBatch}
                disabled={hlsCancelBusy}
              >
                {hlsCancelBusy ? "Stopping..." : "Stop HLS batch"}
              </button>
            )}
          </div>
        )}

        <nav className="lib-tabs">
          <button className={tab === "all" ? "tab-btn active" : "tab-btn"} onClick={handleShowAll}>
            All Videos
          </button>
          <button className={tab === "folders" ? "tab-btn active" : "tab-btn"} onClick={() => setTab("folders")}>
            Folders
          </button>
          <button className={tab === "continue" ? "tab-btn active" : "tab-btn"} onClick={() => setTab("continue")}>
            Continue Watching
            {continueWatching.length > 0 && <span className="tab-badge">{continueWatching.length}</span>}
          </button>
          <button className={tab === "recent" ? "tab-btn active" : "tab-btn"} onClick={() => setTab("recent")}>
            Recently Added
          </button>
          <button className={tab === "duplicates" ? "tab-btn active" : "tab-btn"} onClick={() => setTab("duplicates")}>
            Duplicates
            {duplicateSummary && duplicateSummary.candidate_groups_found > 0 && (
              <span className="tab-badge">{duplicateSummary.candidate_groups_found}</span>
            )}
          </button>
          <button className={tab === "diagnostics" ? "tab-btn active" : "tab-btn"} onClick={() => setTab("diagnostics")}>
            Diagnostics
          </button>
        </nav>

        {tab === "all" && (
          <div className="toolbar toolbar-inline">
            <SearchBar value={search} onChange={setSearch} />
            <SortSelect sort={sort} order={order} onChange={handleSortChange} />
            <div className="compat-chip-row">
              <button className={playbackFilter === "all" ? "filter-chip active" : "filter-chip"} onClick={() => applyCompatibilityFilter("all")}>All</button>
              <button className={playbackFilter === "direct_play" ? "filter-chip active" : "filter-chip"} onClick={() => applyCompatibilityFilter("direct_play")}>Direct Play</button>
              <button className={playbackFilter === "may_play" ? "filter-chip active" : "filter-chip"} onClick={() => applyCompatibilityFilter("may_play")}>May Play</button>
              <button className={playbackFilter === "may_not_play" ? "filter-chip active" : "filter-chip"} onClick={() => applyCompatibilityFilter("may_not_play")}>May Not Play</button>
              <button className={playbackFilter === "needs_conversion" ? "filter-chip active" : "filter-chip"} onClick={() => applyCompatibilityFilter("needs_conversion")}>Needs Conversion</button>
              <button className={playbackFilter === "unknown" ? "filter-chip active" : "filter-chip"} onClick={() => applyCompatibilityFilter("unknown")}>Unknown</button>
            </div>
          </div>
        )}

        {tab === "duplicates" && (
          <div className="duplicates-sticky-header">
            <div className="duplicates-summary">
              <div className="duplicate-summary-card">
                <strong>Status</strong>
                <span>{duplicateStatus?.status ?? duplicateSummary?.last_scan_status ?? "idle"}</span>
              </div>
              <div className="duplicate-summary-card">
                <strong>Mode</strong>
                <span>{duplicateMode}</span>
              </div>
              <div className="duplicate-summary-card">
                <strong>Videos checked</strong>
                <span>{duplicateStatus?.videos_checked ?? Number(duplicateStatus?.last_result_summary?.videos_checked ?? 0)}</span>
              </div>
              <div className="duplicate-summary-card">
                <strong>Groups found</strong>
                <span>{duplicateSummary?.candidate_groups_found ?? duplicateStatus?.candidate_groups_found ?? 0}</span>
              </div>
              <div className="duplicate-summary-card">
                <strong>Duplicate candidates</strong>
                <span>{duplicateSummary?.duplicate_candidates_found ?? duplicateStatus?.duplicate_candidates_found ?? 0}</span>
              </div>
              <div className="duplicate-summary-card">
                <strong>Potential saving</strong>
                <span>{formatBytes(duplicateSummary?.potential_saving ?? 0)}</span>
              </div>
            </div>
            <div className="duplicates-bulk-actions">
              <div className="duplicates-selected-stats">
                Selected: <strong>{selectedDuplicateVideos.length}</strong>
                {" "}video(s) • Total size: <strong>{formatBytes(selectedDuplicateTotalSize)}</strong>
              </div>
              <div className="duplicates-bulk-buttons">
                <button
                  className="btn-secondary"
                  onClick={() => setSelectedDuplicateIds(new Set())}
                  disabled={selectedDuplicateVideos.length === 0 || deletingVideoId !== null}
                >
                  Clear selection
                </button>
                <button
                  className="btn-danger"
                  onClick={() => setShowDeleteConfirm(true)}
                  disabled={selectedDuplicateVideos.length === 0 || deletingVideoId !== null}
                >
                  {deletingVideoId === -1 ? "Deleting..." : `Delete selected (${selectedDuplicateVideos.length})`}
                </button>
              </div>
            </div>
          </div>
        )}

        {tab === "folders" && <div className="tabs-spacer" />}
        {tab === "continue" && <div className="tabs-spacer" />}
        {tab === "recent" && <div className="tabs-spacer" />}
        {tab === "diagnostics" && <div className="tabs-spacer" />}
      </div>

      {tab === "all" && (
        <>
          {loading ? (
            <div className="status">Loading videos…</div>
          ) : videos.length === 0 ? (
            <div className="status">No videos found. Click Scan Library to index your files.</div>
          ) : (
            <div className="video-group-list">
              {groupedVideos.map((group) => (
                <section key={group.key} className="video-group-section">
                  <button className="video-group-header video-group-toggle" onClick={() => toggleVideoGroup(group.key)}>
                    <span>{collapsedVideoGroups.has(group.key) ? ">" : "v"}</span>
                    <span>{group.title} - {group.videos.length} videos</span>
                  </button>
                  {!collapsedVideoGroups.has(group.key) && (
                    <div className="video-grid video-grid-grouped">
                      {group.videos.map((video) => (
                        <VideoCard key={video.id} video={video} progress={progressMap[video.id]} />
                      ))}
                    </div>
                  )}
                </section>
              ))}
            </div>
          )}
        </>
      )}

      {tab === "folders" && (
        <div className="folders-panel">
          <div className="toolbar toolbar-inline folder-sort-toolbar">
            <SortSelect sort={sort} order={order} onChange={handleSortChange} />
          </div>
          {folderLoading ? (
            <div className="status">Loading folders...</div>
          ) : folderTree.children.length === 0 && folderTree.videos.length === 0 ? (
            <div className="status">No folders found. Scan your library first.</div>
          ) : (
            <FolderTree
              root={folderTree}
              expandedPaths={expandedFolders}
              onToggle={toggleFolder}
              progressByVideoId={progressMap}
              sort={sort}
              order={order}
            />
          )}
        </div>
      )}

      {tab === "continue" && (
        <>
          {continueWatching.length === 0 ? (
            <div className="status">No videos in progress. Start watching something!</div>
          ) : (
            <section className="video-grid">
              {continueWatching.map((video) => (
                <VideoCard key={video.id} video={video} progress={video.progress} />
              ))}
            </section>
          )}
        </>
      )}

      {tab === "recent" && (
        <>
          {loading ? (
            <div className="status">Loading recently added videos…</div>
          ) : videos.length === 0 ? (
            <div className="status">No recently added videos yet.</div>
          ) : (
            <section className="video-grid">
              {videos.slice(0, 30).map((video) => (
                <VideoCard key={video.id} video={video} progress={progressMap[video.id]} />
              ))}
            </section>
          )}
        </>
      )}

      {tab === "diagnostics" && (
        <div className="diagnostics-panel">
          <div className="diagnostics-summary-grid">
            <button className="diagnostics-card" onClick={() => applyDiagnosticFilter({})}>
              <strong>Total indexed</strong>
              <span>{librarySummary?.total_indexed ?? 0}</span>
            </button>
            <button className="diagnostics-card" onClick={() => applyDiagnosticFilter({ compatibility_status: "direct_play" })}>
              <strong>Direct Play</strong>
              <span>{librarySummary?.direct_play ?? 0}</span>
            </button>
            <button className="diagnostics-card" onClick={() => applyDiagnosticFilter({ compatibility_status: "may_play" })}>
              <strong>May Play</strong>
              <span>{librarySummary?.may_play ?? 0}</span>
            </button>
            <button className="diagnostics-card" onClick={() => applyDiagnosticFilter({ compatibility_status: "may_not_play" })}>
              <strong>May Not Play</strong>
              <span>{librarySummary?.may_not_play ?? 0}</span>
            </button>
            <button className="diagnostics-card" onClick={() => applyDiagnosticFilter({ compatibility_status: "needs_conversion" })}>
              <strong>Needs Conversion</strong>
              <span>{librarySummary?.needs_conversion ?? 0}</span>
            </button>
            <button className="diagnostics-card" onClick={() => applyDiagnosticFilter({ compatibility_status: "unknown" })}>
              <strong>Unknown</strong>
              <span>{librarySummary?.unknown_compatibility ?? 0}</span>
            </button>
            <button className="diagnostics-card" onClick={() => applyDiagnosticFilter({ media_status: "probe_failed_possible_video" })}>
              <strong>Probe Failed</strong>
              <span>{librarySummary?.probe_failed_possible_video ?? 0}</span>
            </button>
            <button className="diagnostics-card" onClick={() => applyDiagnosticFilter({ thumbnail_status: "failed" })}>
              <strong>Thumbnail Failed</strong>
              <span>{librarySummary?.thumbnail_failed ?? 0}</span>
            </button>
            <button className="diagnostics-card" onClick={() => setTab("duplicates")}>
              <strong>Potential duplicate saving</strong>
              <span>{formatBytes(librarySummary?.last_duplicate_scan.potential_saving ?? 0)}</span>
            </button>
            <button className="diagnostics-card" onClick={() => { setProfileOnlyMissingManual(true); }}>
              <strong>Profiles pending manual check</strong>
              <span>{librarySummary?.media_profiles_pending_manual_check ?? 0}</span>
            </button>
          </div>

          <section className="diagnostics-section">
            <div className="diagnostics-section-header">
              <h3>HLS State</h3>
              <button className="btn-secondary" onClick={onRepairStaleHls} disabled={hlsRepairBusy}>
                {hlsRepairBusy ? "Repairing..." : "Repair HLS state"}
              </button>
            </div>
            <div className="diagnostics-summary-grid">
              <button className="diagnostics-card" type="button">
                <strong>Valid HLS</strong>
                <span>{hlsDiagnostics?.valid_hls ?? 0}</span>
              </button>
              <button className="diagnostics-card" type="button">
                <strong>Missing HLS</strong>
                <span>{hlsDiagnostics?.missing_hls ?? 0}</span>
              </button>
              <button className="diagnostics-card" type="button">
                <strong>Stale completed</strong>
                <span>{hlsDiagnostics?.db_completed_but_files_missing ?? 0}</span>
              </button>
              <button className="diagnostics-card" type="button">
                <strong>Stale queued</strong>
                <span>{hlsDiagnostics?.stale_queued ?? 0}</span>
              </button>
              <button className="diagnostics-card" type="button">
                <strong>Stale running</strong>
                <span>{hlsDiagnostics?.stale_running ?? 0}</span>
              </button>
              <button className="diagnostics-card" type="button">
                <strong>Source missing</strong>
                <span>{hlsDiagnostics?.invalid_source_missing ?? 0}</span>
              </button>
            </div>
          </section>

          <section className="diagnostics-section">
            <div className="diagnostics-section-header">
              <h3>Unique Media Profiles</h3>
              <span className="diagnostics-hint">Auto guess + manual calibration matrix</span>
            </div>
            <div className="media-profiles-toolbar">
              <label>
                Effective
                <select value={profileEffectiveFilter} onChange={(event) => setProfileEffectiveFilter(event.target.value)}>
                  <option value="all">All</option>
                  <option value="direct_play">Direct Play</option>
                  <option value="may_play">May Play</option>
                  <option value="may_not_play">May Not Play</option>
                  <option value="needs_conversion">Needs Conversion</option>
                  <option value="unknown">Unknown</option>
                </select>
              </label>
              <label>
                Extension
                <input
                  value={profileExtensionFilter}
                  onChange={(event) => setProfileExtensionFilter(event.target.value)}
                  placeholder=".360"
                />
              </label>
              <label>
                Sort
                <select value={profileSort} onChange={(event) => setProfileSort(event.target.value as ProfileSort)}>
                  <option value="default">Missing manual first, files count desc</option>
                  <option value="files_count_desc">Files count desc</option>
                  <option value="extension">Extension</option>
                  <option value="effective_status">Effective status</option>
                </select>
              </label>
              <label className="checkbox-inline">
                <input
                  type="checkbox"
                  checked={profileOnlyMissingManual}
                  onChange={(event) => setProfileOnlyMissingManual(event.target.checked)}
                />
                Manual status missing only
              </label>
            </div>

            {filteredMediaProfiles.length === 0 ? (
              <p className="status">
                {profileOnlyMissingManual
                  ? "All media profiles are already manually checked. Disable the filter to view reviewed profiles."
                  : "No media profiles found for current filters."}
              </p>
            ) : (
              <div className="media-profile-list">
                {filteredMediaProfiles.map((profile) => (
                  <article key={profile.id} className="media-profile-item">
                    <div className="media-profile-main">
                      <div className="media-profile-identity">
                        <strong>{profile.extension} • {profile.video_codec} • {profile.audio_codec}</strong>
                        <p>{profile.container_format}</p>
                        <p>
                          video profile {profile.video_profile}, level {profile.video_level}, pix_fmt {profile.pixel_format},
                          {" "}audio ch {profile.audio_channels ?? "unknown"}, sample rate {profile.audio_sample_rate ?? "unknown"},
                          {" "}{profile.width_bucket}x{profile.height_bucket}
                        </p>
                      </div>
                      <div className="media-profile-statuses">
                        <p><strong>Auto guess:</strong> {profile.auto_compatibility_status}</p>
                        <p><strong>Manual profile status:</strong> {profile.manual_playback_status ?? "not set"}</p>
                        <p><strong>Effective status:</strong> {profile.effective_compatibility_status}</p>
                        <p><strong>Source:</strong> {profile.compatibility_source}</p>
                        <p><strong>Files:</strong> {profile.files_count}</p>
                      </div>
                    </div>

                    {profile.sample_video && (
                      <div className="media-profile-sample">
                        <a href={profile.sample_video.watch_url} target="_blank" rel="noopener noreferrer" className="media-profile-sample-link">
                          {profile.sample_video.thumbnail_url ? (
                            <img src={profile.sample_video.thumbnail_url} alt={profile.sample_video.title} loading="lazy" />
                          ) : (
                            <div className="thumb placeholder">No Thumbnail</div>
                          )}
                        </a>
                        <div>
                          <a href={profile.sample_video.watch_url} target="_blank" rel="noopener noreferrer" className="media-profile-sample-title">
                            Open sample in new tab
                          </a>
                          <p>{profile.sample_video.title}</p>
                          <p>{profile.sample_video.relative_path}</p>
                        </div>
                      </div>
                    )}

                    <div className="media-profile-actions">
                      <button className="btn-secondary" disabled={profileActionBusyId === profile.id} onClick={() => onSetProfileStatus(profile.id, "playable")}>Mark Playable</button>
                      <button className="btn-secondary" disabled={profileActionBusyId === profile.id} onClick={() => onSetProfileStatus(profile.id, "not_playable")}>Mark Not Playable</button>
                      <button className="btn-secondary" disabled={profileActionBusyId === profile.id} onClick={() => onSetProfileStatus(profile.id, "partially_playable")}>Mark Partially Playable</button>
                      <button className="btn-secondary" disabled={profileActionBusyId === profile.id} onClick={() => onSetProfileStatus(profile.id, "unknown")}>Mark Unknown</button>
                      <button className="btn-danger" disabled={profileActionBusyId === profile.id} onClick={() => onClearProfileStatus(profile.id)}>Clear Manual Override</button>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>

          <section className="diagnostics-section">
            <div className="diagnostics-section-header">
              <h3>Probe failed files</h3>
              <button className="btn-secondary" onClick={() => applyDiagnosticFilter({ probe_status: "failed" })}>View all</button>
            </div>
            {probeFailedFiles.length === 0 ? (
              <p className="status">No probe-failed files.</p>
            ) : (
              probeFailedFiles.map((video) => (
                <a key={video.id} className="diagnostics-item" href={`/watch/${video.id}`} target="_blank" rel="noopener noreferrer">
                  <div className="thumb placeholder">No Thumbnail</div>
                  <div>
                    <strong>{video.title}</strong>
                    <p>{video.filename}</p>
                    <p>{video.extension} • {formatBytes(video.size)} • indexed {new Date(video.indexed_at).toLocaleString()}</p>
                    <p>{video.probe_error ?? "No probe error details"}</p>
                  </div>
                </a>
              ))
            )}
          </section>

          <section className="diagnostics-section">
            <div className="diagnostics-section-header">
              <h3>Needs conversion files</h3>
              <button className="btn-secondary" onClick={() => applyDiagnosticFilter({ compatibility_status: "needs_conversion" })}>View all</button>
            </div>
            {needsConversionFiles.length === 0 ? (
              <p className="status">No files needing conversion.</p>
            ) : (
              needsConversionFiles.map((video) => (
                <a key={video.id} className="diagnostics-item" href={`/watch/${video.id}`} target="_blank" rel="noopener noreferrer">
                  <div>
                    <strong>{video.title}</strong>
                    <p>{video.filename}</p>
                    <p>{video.extension} • {video.video_codec ?? "unknown"} / {video.audio_codec ?? "unknown"}</p>
                    <p>{video.width && video.height ? `${video.width}x${video.height}` : "Unknown resolution"}</p>
                    <p>{video.compatibility_reason ?? ""}</p>
                  </div>
                </a>
              ))
            )}
          </section>

          <section className="diagnostics-section">
            <div className="diagnostics-section-header">
              <h3>Unknown compatibility files</h3>
              <button className="btn-secondary" onClick={() => applyDiagnosticFilter({ compatibility_status: "unknown" })}>View all</button>
            </div>
            {unknownCompatibilityFiles.length === 0 ? (
              <p className="status">No unknown compatibility files.</p>
            ) : (
              unknownCompatibilityFiles.map((video) => (
                <a key={video.id} className="diagnostics-item" href={`/watch/${video.id}`} target="_blank" rel="noopener noreferrer">
                  <div>
                    <strong>{video.title}</strong>
                    <p>{video.filename}</p>
                    <p>{video.extension} • {video.container_format ?? "Unknown container"}</p>
                    {video.probe_error && <p>{video.probe_error}</p>}
                  </div>
                </a>
              ))
            )}
          </section>

          <section className="diagnostics-section">
            <div className="diagnostics-section-header">
              <h3>Thumbnail failed files</h3>
              <button className="btn-secondary" onClick={() => applyDiagnosticFilter({ thumbnail_status: "failed" })}>View all</button>
            </div>
            {thumbnailFailedFiles.length === 0 ? (
              <p className="status">No thumbnail failures.</p>
            ) : (
              thumbnailFailedFiles.map((video) => (
                <a key={video.id} className="diagnostics-item" href={`/watch/${video.id}`} target="_blank" rel="noopener noreferrer">
                  <div>
                    <strong>{video.title}</strong>
                    <p>{video.filename}</p>
                    <p>{video.thumbnail_error ?? "No thumbnail error details"}</p>
                  </div>
                </a>
              ))
            )}
          </section>
        </div>
      )}

      {tab === "duplicates" && (
        <div className="duplicates-panel">
          {duplicateStatus?.status === "running" && (
            <div className="notice">
              Scanning duplicate candidates...
              {duplicateStatus.current_step ? ` ${duplicateStatus.current_step}` : ""}
            </div>
          )}

          {duplicateSummary?.is_outdated && duplicateStatus?.status !== "running" && (
            <div className="notice notice-warning">
              ⚠ Duplicate results may be outdated — the library was scanned since the last duplicate scan. Click <strong>Scan Duplicates</strong> to refresh.
            </div>
          )}

          {duplicateStatus?.errors && duplicateStatus.errors.length > 0 && (
            <div className="error">{duplicateStatus.errors.join(" | ")}</div>
          )}

          {duplicateLoading ? (
            <div className="status">Loading duplicate results…</div>
          ) : duplicateSummary?.last_scan_status === "idle" && duplicateGroups.length === 0 ? (
            <div className="status">
              Duplicate scan has not been run yet. Click Scan Duplicates to find possible duplicate videos.
            </div>
          ) : duplicateSummary && !["idle", "outdated"].includes(duplicateSummary.last_scan_status) && duplicateGroups.length === 0 ? (
            <div className="status">No duplicate candidates found.</div>
          ) : duplicateSummary?.last_scan_status === "outdated" && duplicateGroups.length === 0 ? (
            <div className="status">No duplicate candidates from previous scan. Results may be outdated.</div>
          ) : (
            <div className="duplicate-groups">
              {duplicateGroups.map((group, index) => (
                <section key={group.group_id} className="duplicate-group-card">
                  <div className="duplicate-group-header">
                    <div>
                      <h3>Group {index + 1}</h3>
                      <p className="duplicate-reason">{group.reason}</p>
                    </div>
                    <span className={`duplicate-confidence badge-${group.confidence}`}>
                      {confidenceLabel(group.confidence)}
                    </span>
                  </div>

                  <div className="duplicate-fingerprint-grid">
                    <div><strong>Count:</strong> {group.candidate_count}</div>
                    <div><strong>Total size:</strong> {formatBytes(group.total_size)}</div>
                    <div><strong>Potential saving:</strong> {formatBytes(group.potential_saving)}</div>
                    <div><strong>Duration:</strong> {formatDuration(group.fingerprint.duration_seconds)}</div>
                    <div><strong>Resolution:</strong> {group.fingerprint.width && group.fingerprint.height ? `${group.fingerprint.width}×${group.fingerprint.height}` : "Unknown"}</div>
                    <div><strong>Video codec:</strong> {group.fingerprint.video_codec ?? "Unknown"}</div>
                    <div><strong>Audio codec:</strong> {group.fingerprint.audio_codec ?? "Unknown"}</div>
                    <div><strong>Container:</strong> {group.fingerprint.extension ?? "Unknown"}</div>
                  </div>

                  <div className="duplicate-video-list">
                    {group.videos.map((video) => (
                      <article key={video.id} className="duplicate-video-item">
                        <div className="duplicate-video-select">
                          <input
                            type="checkbox"
                            checked={selectedDuplicateIds.has(video.id)}
                            onChange={() => toggleDuplicateSelection(video.id)}
                            disabled={deletingVideoId !== null}
                            aria-label={`Select ${video.relative_path} for deletion`}
                          />
                        </div>
                        <div className="duplicate-video-thumb">
                          {video.thumbnail_url ? (
                            <img src={video.thumbnail_url} alt={video.title} loading="lazy" />
                          ) : (
                            <div className="thumb placeholder">No Thumbnail</div>
                          )}
                        </div>
                        <div className="duplicate-video-body">
                          <a href={video.watch_url} target="_blank" rel="noopener noreferrer" className="duplicate-video-link">
                            {video.title}
                          </a>
                          <p>{video.relative_path}</p>
                          <p>
                            {formatBytes(video.size)} • {formatDuration(video.duration)} • {video.width && video.height ? `${video.width}×${video.height}` : "Unknown"}
                          </p>
                          <p>
                            {(video.video_codec ?? "unknown")} / {(video.audio_codec ?? "unknown")} • {video.extension.toUpperCase()}
                          </p>
                          <div className="duplicate-video-actions">
                            <button
                              className="btn-danger duplicate-delete-btn"
                              onClick={() => onDeleteDuplicateVideoClick(video.id)}
                              disabled={deletingVideoId === video.id || deletingVideoId === -1}
                            >
                              {deletingVideoId === video.id ? "Deleting..." : "Delete this video"}
                            </button>
                          </div>
                        </div>
                      </article>
                    ))}
                  </div>
                </section>
              ))}
            </div>
          )}
        </div>
      )}

      {showDeleteConfirm && (
        <div className="modal-backdrop" onClick={() => (deletingVideoId === null ? setShowDeleteConfirm(false) : null)}>
          <div className="modal-card" onClick={(event) => event.stopPropagation()}>
            <h3>Delete selected files?</h3>
            <p>
              You selected <strong>{selectedDuplicateVideos.length}</strong> file(s), total size <strong>{formatBytes(selectedDuplicateTotalSize)}</strong>.
            </p>
            <p>This action will remove files from the source folder and index.</p>
            {deletingVideoId === -1 && bulkDeleteProgress && (
              <div className="modal-progress">
                <div className="modal-progress-row">
                  <span>Deleting files...</span>
                  <span>{bulkDeleteProgress.done}/{bulkDeleteProgress.total}</span>
                </div>
                <div className="progress-track" aria-hidden="true">
                  <div
                    className="progress-fill"
                    style={{ width: `${Math.round((bulkDeleteProgress.done / bulkDeleteProgress.total) * 100)}%` }}
                  />
                </div>
              </div>
            )}
            <div className="modal-file-list-wrap">
              <ul className="modal-file-list">
                {selectedDuplicateVideos.map((video) => (
                  <li key={video.id}>
                    <span>{video.relative_path}</span>
                    <span>{formatBytes(video.size)}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div className="modal-actions">
              <button
                className="btn-secondary"
                onClick={() => setShowDeleteConfirm(false)}
                disabled={deletingVideoId !== null}
              >
                Cancel
              </button>
              <button className="btn-danger" onClick={onConfirmDeleteSelected} disabled={deletingVideoId !== null}>
                {deletingVideoId === -1
                  ? `Deleting ${bulkDeleteProgress?.done ?? 0}/${bulkDeleteProgress?.total ?? 0}...`
                  : "Yes, delete files"}
              </button>
            </div>
          </div>
        </div>
      )}

      {showHlsLibraryConfirm && (
        <div className="modal-backdrop" onClick={() => (hlsBatchBusy ? null : setShowHlsLibraryConfirm(false))}>
          <div className="modal-card" onClick={(event) => event.stopPropagation()}>
            <h3>Prepare HLS for all missing videos?</h3>
            <p>
              This will enqueue HLS generation for all indexed videos without completed HLS.
              Existing HLS can be skipped by default.
            </p>
            <p>
              This may take many hours on Synology DS923+. Only one HLS job runs at a time by default.
              Original files will not be modified.
            </p>
            <label className="checkbox-inline" style={{ display: "block", marginBottom: 8 }}>
              <input
                type="checkbox"
                checked={hlsSkipExisting}
                onChange={(event) => setHlsSkipExisting(event.target.checked)}
                disabled={hlsBatchBusy || hlsForceRegenerate}
              />
              Skip videos with existing HLS
            </label>
            <label className="checkbox-inline" style={{ display: "block", marginBottom: 8 }}>
              <input
                type="checkbox"
                checked={hlsForceRegenerate}
                onChange={(event) => {
                  const force = event.target.checked;
                  setHlsForceRegenerate(force);
                  if (force) {
                    setHlsSkipExisting(false);
                  }
                }}
                disabled={hlsBatchBusy}
              />
              Force regenerate existing HLS (slower)
            </label>
            <div className="modal-actions" style={{ marginTop: 12 }}>
              <button className="btn-secondary" onClick={() => setShowHlsLibraryConfirm(false)} disabled={hlsBatchBusy}>
                Cancel
              </button>
              <button className="btn-primary" onClick={onStartLibraryHlsBatch} disabled={hlsBatchBusy}>
                {hlsBatchBusy ? "Starting..." : "Start"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
