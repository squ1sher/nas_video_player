import { useEffect, useMemo, useRef, useState } from "react";
import {
  deleteVideo,
  fetchVideos,
  getContinueWatching,
  getDuplicateGroups,
  getDuplicateStatus,
  getDuplicateSummary,
  getFolders,
  getScanStatus,
  runScan,
  startDuplicateScan,
} from "../api/client";
import type { SortField, SortOrder } from "../api/client";
import { ScanStatusBar } from "../components/ScanStatusBar";
import { SearchBar } from "../components/SearchBar";
import { SortSelect } from "../components/SortSelect";
import { VideoCard } from "../components/VideoCard";
import type {
  DuplicateGroup,
  DuplicateScanStatus,
  DuplicateSummary,
  FolderInfo,
  ScanStatus,
  VideoListItem,
  VideoWithProgress,
} from "../types/video";

type Tab = "all" | "folders" | "continue" | "duplicates";

type FolderNode = {
  name: string;
  path: string;
  videoCount: number;
  children: FolderNode[];
};

function buildFolderTree(items: FolderInfo[]): FolderNode[] {
  const root: FolderNode = { name: "", path: "", videoCount: 0, children: [] };

  const ensureChild = (parent: FolderNode, name: string, path: string): FolderNode => {
    const existing = parent.children.find((child) => child.name === name);
    if (existing) return existing;
    const created: FolderNode = { name, path, videoCount: 0, children: [] };
    parent.children.push(created);
    return created;
  };

  for (const folder of items) {
    const normalized = folder.folder_path.trim();
    if (!normalized) {
      root.videoCount += folder.video_count;
      continue;
    }

    const parts = normalized.split("/").filter(Boolean);
    let current = root;
    let path = "";
    for (const part of parts) {
      path = path ? `${path}/${part}` : part;
      current = ensureChild(current, part, path);
    }
    current.videoCount += folder.video_count;
  }

  const sortTree = (nodes: FolderNode[]) => {
    nodes.sort((a, b) => a.name.localeCompare(b.name));
    nodes.forEach((node) => sortTree(node.children));
  };

  sortTree(root.children);
  return root.children;
}

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
  const [folders, setFolders] = useState<FolderInfo[]>([]);
  const [selectedFolder, setSelectedFolder] = useState<string | null>(null);
  const [scanStatus, setScanStatus] = useState<ScanStatus | null>(null);
  const [duplicateStatus, setDuplicateStatus] = useState<DuplicateScanStatus | null>(null);
  const [duplicateSummary, setDuplicateSummary] = useState<DuplicateSummary | null>(null);
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
  const [search, setSearch] = useState("");
  const [playbackFilter, setPlaybackFilter] = useState<string>("all");
  const [sort, setSort] = useState<SortField>("created_at");
  const [order, setOrder] = useState<SortOrder>("desc");
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set());
  const libraryPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const duplicatePollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const folderTree = useMemo(() => buildFolderTree(folders), [folders]);
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

  const loadVideos = async () => {
    try {
      setLoading(true);
      setError(null);
      const q = search.trim() || undefined;
      const folder = selectedFolder !== null ? selectedFolder : undefined;
      const compatibility_status = playbackFilter !== "all" ? playbackFilter : undefined;
      setVideos(await fetchVideos({ q, folder, compatibility_status, sort, order }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load videos");
    } finally {
      setLoading(false);
    }
  };

  const loadContinueWatching = async () => {
    try {
      setContinueWatching(await getContinueWatching());
    } catch {
      // non-critical
    }
  };

  const loadFolders = async () => {
    try {
      setFolders(await getFolders());
    } catch {
      // non-critical
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

  const startLibraryPolling = () => {
    if (libraryPollRef.current) return;
    libraryPollRef.current = setInterval(async () => {
      try {
        const status = await getScanStatus();
        setScanStatus(status);
        if (status.status !== "running") {
          stopLibraryPolling();
          if (status.status === "completed") {
            await Promise.all([loadVideos(), loadContinueWatching(), loadFolders()]);
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
  }, [search, playbackFilter, sort, order, selectedFolder]);

  useEffect(() => {
    void loadContinueWatching();
    void loadFolders();
    getScanStatus()
      .then((status) => {
        setScanStatus(status);
        if (status.status === "running") startLibraryPolling();
      })
      .catch(() => {});
    return () => stopLibraryPolling();
  }, []);

  useEffect(() => {
    void loadDuplicateData();
    return () => stopDuplicatePolling();
  }, []);

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

  const handleFolderSelect = (path: string) => {
    setSelectedFolder(path);
    setTab("all");
  };

  const handleShowAll = () => {
    setSelectedFolder(null);
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
    try {
      setError(null);
      await runScan();
      const status = await getScanStatus();
      setScanStatus(status);
      if (status.status === "running") startLibraryPolling();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Scan failed");
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
      await Promise.all([loadDuplicateData(), loadVideos(), loadContinueWatching(), loadFolders()]);
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
      await Promise.all([loadDuplicateData(), loadVideos(), loadContinueWatching(), loadFolders()]);
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

  const renderFolderNode = (node: FolderNode) => {
    const hasChildren = node.children.length > 0;
    const isExpanded = expandedFolders.has(node.path);
    return (
      <li key={node.path} className="folder-tree-node">
        <div className="folder-tree-row">
          {hasChildren ? (
            <button className="folder-toggle" onClick={() => toggleFolder(node.path)}>
              {isExpanded ? "▾" : "▸"}
            </button>
          ) : (
            <span className="folder-toggle-placeholder" />
          )}
          <button className="folder-tree-item" onClick={() => handleFolderSelect(node.path)}>
            <span className="folder-icon">📁</span>
            <span className="folder-name">{node.name}</span>
            <span className="folder-count">{node.videoCount} videos</span>
          </button>
        </div>
        {hasChildren && isExpanded && (
          <ul className="folder-tree-children">{node.children.map((child) => renderFolderNode(child))}</ul>
        )}
      </li>
    );
  };

  return (
    <div className="page">
      <div className="library-sticky-shell">
        <header className="page-header page-header-actions">
          <h1>NAS Video Player</h1>
          <div className="header-actions">
            <button onClick={onScanClick} disabled={scanStatus?.status === "running"}>
              {scanStatus?.status === "running" ? "Scanning…" : "Scan Library"}
            </button>
            <div className="duplicate-actions">
              <button onClick={onDuplicateScanClick} disabled={duplicateStatus?.status === "running"}>
                {duplicateStatus?.status === "running" ? "Scanning duplicates…" : "Scan Duplicates"}
              </button>
            </div>
          </div>
        </header>

        <ScanStatusBar status={scanStatus} />
        {error && <div className="error">{error}</div>}
        {duplicateError && <div className="error">{duplicateError}</div>}

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
          <button className={tab === "duplicates" ? "tab-btn active" : "tab-btn"} onClick={() => setTab("duplicates")}>
            Duplicates
            {duplicateSummary && duplicateSummary.candidate_groups_found > 0 && (
              <span className="tab-badge">{duplicateSummary.candidate_groups_found}</span>
            )}
          </button>
        </nav>

        {tab === "all" && (
          <div className="toolbar toolbar-inline">
            <SearchBar value={search} onChange={setSearch} />
            <select
              className="playback-filter-select"
              value={playbackFilter}
              onChange={(event) => setPlaybackFilter(event.target.value)}
            >
              <option value="all">All playback capabilities</option>
              <option value="direct_play">Direct Play</option>
              <option value="may_play">May Play</option>
              <option value="may_not_play">May Not Play</option>
              <option value="needs_conversion">Needs Conversion</option>
              <option value="unknown">Unknown</option>
            </select>
            <SortSelect sort={sort} order={order} onChange={handleSortChange} />
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
      </div>

      {tab === "all" && (
        <>
          {selectedFolder !== null && (
            <div className="folder-breadcrumb">
              <button className="link-btn" onClick={handleShowAll}>All Videos</button>
              {" / "}
              <strong>{selectedFolder || "Root"}</strong>
            </div>
          )}
          {loading ? (
            <div className="status">Loading videos…</div>
          ) : videos.length === 0 ? (
            <div className="status">No videos found. Click Scan Library to index your files.</div>
          ) : (
            <section className="video-grid">
              {videos.map((video) => (
                <VideoCard key={video.id} video={video} progress={progressMap[video.id]} />
              ))}
            </section>
          )}
        </>
      )}

      {tab === "folders" && (
        <div className="folders-panel">
          {folders.length === 0 ? (
            <div className="status">No folders found. Scan your library first.</div>
          ) : (
            <>
              <button className="folder-item folder-root-item" onClick={() => handleFolderSelect("")}>
                <span className="folder-icon">📁</span>
                <span className="folder-name">Root</span>
                <span className="folder-count">{folders.find((item) => item.folder_path === "")?.video_count ?? 0} videos</span>
              </button>
              <ul className="folder-tree-list">{folderTree.map((node) => renderFolderNode(node))}</ul>
            </>
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

      {tab === "duplicates" && (
        <div className="duplicates-panel">
          {duplicateStatus?.status === "running" && (
            <div className="notice">
              Scanning duplicate candidates...
              {duplicateStatus.current_step ? ` ${duplicateStatus.current_step}` : ""}
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
          ) : duplicateSummary && duplicateSummary.last_scan_status !== "idle" && duplicateGroups.length === 0 ? (
            <div className="status">No duplicate candidates found.</div>
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
    </div>
  );
}
