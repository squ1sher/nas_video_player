import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { bulkAssignTags, bulkDeleteVideos, fetchVideos } from "../api/client";
import type { SortField, SortOrder } from "../api/client";
import { SearchBar } from "../components/SearchBar";
import { SortSelect } from "../components/SortSelect";
import { VideoCard } from "../components/VideoCard";
import { FolderTree } from "../components/folders/FolderTree";
import { TagSelectorDialog } from "../components/tags/TagSelectorDialog";
import type { VideoBulkDeleteResult, VideoListItem } from "../types/video";
import { buildFolderTree } from "../utils/buildFolderTree";
import { groupVideos } from "../utils/groupVideos";

type Tab = "all" | "folders";

type SourceGroup = {
  key: string;
  name: string;
  videos: VideoListItem[];
};

type VisibleGroup = {
  key: string;
  title: string;
  videos: VideoListItem[];
  totalCount: number;
};

const LIBRARY_INITIAL_ITEMS = 60;
const LIBRARY_LOAD_MORE_ITEMS = 60;

function sourceLabel(video: VideoListItem): string {
  return video.library_root_name || "Unassigned source";
}

function sourceKey(video: VideoListItem): string {
  return `${video.library_root_id ?? "none"}:${sourceLabel(video)}`;
}

function formatSize(bytes: number): string {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

export function LibraryPage() {
  const navigate = useNavigate();
  const menuRef = useRef<HTMLDivElement | null>(null);
  const [tab, setTab] = useState<Tab>("all");
  const [videos, setVideos] = useState<VideoListItem[]>([]);
  const [folderVideos, setFolderVideos] = useState<VideoListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [folderLoading, setFolderLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortField>("file_modified_at");
  const [order, setOrder] = useState<SortOrder>("desc");
  const [visibleCount, setVisibleCount] = useState(LIBRARY_INITIAL_ITEMS);
  const [collapsedVideoGroups, setCollapsedVideoGroups] = useState<Set<string>>(new Set());
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set());
  const [menuOpen, setMenuOpen] = useState(false);
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [tagDialogOpen, setTagDialogOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [bulkDeleteBusy, setBulkDeleteBusy] = useState(false);
  const [bulkDeleteResult, setBulkDeleteResult] = useState<VideoBulkDeleteResult | null>(null);
  const [actionNotice, setActionNotice] = useState<string | null>(null);

  const groupedVideos = useMemo(() => groupVideos(videos, { sort, order }), [videos, sort, order]);

  const visibleGroupedVideos = useMemo<VisibleGroup[]>(() => {
    let remaining = visibleCount;
    const result: VisibleGroup[] = [];
    for (const group of groupedVideos) {
      if (remaining <= 0) break;
      const visibleVideos = group.videos.slice(0, remaining);
      if (visibleVideos.length > 0) {
        result.push({
          key: group.key,
          title: group.title,
          videos: visibleVideos,
          totalCount: group.videos.length,
        });
        remaining -= visibleVideos.length;
      }
    }
    return result;
  }, [groupedVideos, visibleCount]);

  const totalVisibleVideos = useMemo(
    () => visibleGroupedVideos.reduce((count, group) => count + group.videos.length, 0),
    [visibleGroupedVideos]
  );

  const canLoadMoreVideos = totalVisibleVideos < videos.length;

  const visibleVideos = useMemo(() => {
    if (tab === "all") {
      return visibleGroupedVideos.flatMap((group) => group.videos);
    }
    return folderVideos;
  }, [folderVideos, tab, visibleGroupedVideos]);

  const selectedVideos = useMemo(() => {
    const selected = selectedIds;
    return visibleVideos.filter((video) => selected.has(video.id));
  }, [selectedIds, visibleVideos]);

  const selectedTotalSize = useMemo(
    () => selectedVideos.reduce((sum, video) => sum + video.size, 0),
    [selectedVideos]
  );

  const folderSourceGroups = useMemo<SourceGroup[]>(() => {
    const map = new Map<string, SourceGroup>();
    for (const video of folderVideos) {
      const key = sourceKey(video);
      const existing = map.get(key);
      if (existing) {
        existing.videos.push(video);
      } else {
        map.set(key, {
          key,
          name: sourceLabel(video),
          videos: [video],
        });
      }
    }
    return [...map.values()].sort((a, b) => a.name.localeCompare(b.name, "en", { sensitivity: "base" }));
  }, [folderVideos]);

  const folderTrees = useMemo(() => {
    return folderSourceGroups.map((group) => ({
      ...group,
      tree: buildFolderTree(group.videos),
    }));
  }, [folderSourceGroups]);

  const loadAllVideos = async () => {
    const queryText = search.trim() || undefined;
    const data = await fetchVideos({ q: queryText, sort, order });
    setVideos(data);
  };

  const loadFolderVideos = async () => {
    const data = await fetchVideos({ sort, order });
    setFolderVideos(data);
  };

  useEffect(() => {
    let isMounted = true;

    const run = async () => {
      try {
        setError(null);
        if (tab === "all") {
          setLoading(true);
          await loadAllVideos();
        } else {
          setFolderLoading(true);
          await loadFolderVideos();
        }
      } catch (err) {
        if (!isMounted) return;
        setError(err instanceof Error ? err.message : "Failed to load library data");
      } finally {
        if (!isMounted) return;
        setLoading(false);
        setFolderLoading(false);
      }
    };

    void run();

    return () => {
      isMounted = false;
    };
  }, [tab, search, sort, order]);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (!menuRef.current) return;
      if (menuRef.current.contains(event.target as Node)) return;
      setMenuOpen(false);
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  useEffect(() => {
    if (!selectionMode) return;
    const validIds = new Set(visibleVideos.map((video) => video.id));
    setSelectedIds((prev) => {
      const next = new Set<number>();
      prev.forEach((id) => {
        if (validIds.has(id)) next.add(id);
      });
      return next;
    });
  }, [selectionMode, visibleVideos]);

  const handleSortChange = (nextSort: SortField, nextOrder: SortOrder) => {
    setSort(nextSort);
    setOrder(nextOrder);
  };

  const toggleVideoGroup = (groupKey: string) => {
    setCollapsedVideoGroups((prev) => {
      const next = new Set(prev);
      if (next.has(groupKey)) next.delete(groupKey);
      else next.add(groupKey);
      return next;
    });
  };

  const toggleFolder = (path: string) => {
    setExpandedFolders((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  const loadMoreVideos = () => {
    setVisibleCount((prev) => prev + LIBRARY_LOAD_MORE_ITEMS);
  };

  useEffect(() => {
    setVisibleCount(LIBRARY_INITIAL_ITEMS);
  }, [tab, search, sort, order]);

  const clearSelectionAndExit = () => {
    setSelectedIds(new Set());
    setSelectionMode(false);
  };

  const toggleSelected = (videoId: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(videoId)) next.delete(videoId);
      else next.add(videoId);
      return next;
    });
  };

  const openSelectionMode = () => {
    setSelectionMode(true);
    setMenuOpen(false);
    setActionNotice(null);
  };

  const openDeleteDialog = () => {
    setDeleteDialogOpen(true);
    setBulkDeleteResult(null);
    setMenuOpen(false);
  };

  const closeDeleteDialog = () => {
    setDeleteDialogOpen(false);
    const result = bulkDeleteResult;
    setBulkDeleteResult(null);
    if (result) {
      clearSelectionAndExit();
    }
  };

  const handleBulkDelete = async () => {
    const ids = selectedVideos.map((video) => video.id);
    if (ids.length === 0) return;

    setBulkDeleteBusy(true);
    try {
      const result = await bulkDeleteVideos(ids);
      setBulkDeleteResult(result);
      if (result.deleted.length > 0) {
        const deleted = new Set(result.deleted);
        setVideos((prev) => prev.filter((video) => !deleted.has(video.id)));
        setFolderVideos((prev) => prev.filter((video) => !deleted.has(video.id)));
      }
    } catch (err) {
      setBulkDeleteResult({
        deleted: [],
        failed: [{ video_id: -1, error: err instanceof Error ? err.message : "Bulk delete failed." }],
      });
    } finally {
      setBulkDeleteBusy(false);
    }
  };

  const handleBulkAssignTags = async (tagIds: number[]) => {
    const videoIds = selectedVideos.map((video) => video.id);
    if (videoIds.length === 0 || tagIds.length === 0) return;

    const result = await bulkAssignTags(videoIds, tagIds);
    await Promise.all([loadAllVideos(), loadFolderVideos()]);
    clearSelectionAndExit();
    setActionNotice(
      `Assigned ${result.tags_assigned} tag(s) to ${result.videos_processed} selected video(s).`
    );
  };

  const selectionLabel = `Selected: ${selectedVideos.length}`;

  return (
    <div className="page page-library-compact">
      <header className="library-compact-header">
        <div className="library-title-mini">Library</div>
        <nav className="lib-tabs lib-tabs-compact">
          <button className={tab === "all" ? "tab-btn active" : "tab-btn"} onClick={() => setTab("all")}>All Videos</button>
          <button className={tab === "folders" ? "tab-btn active" : "tab-btn"} onClick={() => setTab("folders")}>Folders</button>
        </nav>
        <div className="library-controls-compact">
          <SearchBar value={search} onChange={setSearch} />
          <SortSelect sort={sort} order={order} onChange={handleSortChange} />
          {selectionMode ? <span className="library-selected-count">{selectionLabel}</span> : null}

          <div className="library-menu" ref={menuRef}>
            <button className="btn-secondary" onClick={() => setMenuOpen((prev) => !prev)}>Menu</button>
            {menuOpen ? (
              <div className="library-menu-dropdown">
                <button className="library-menu-item" onClick={() => navigate("/settings")}>Settings</button>

                {!selectionMode ? (
                  <button className="library-menu-item" onClick={openSelectionMode}>Select</button>
                ) : (
                  <>
                    <button className="library-menu-item" onClick={() => { clearSelectionAndExit(); setMenuOpen(false); }}>
                      Exit selection
                    </button>
                    <button
                      className="library-menu-item"
                      onClick={() => { setTagDialogOpen(true); setMenuOpen(false); }}
                      disabled={selectedVideos.length === 0}
                    >
                      Add tag to selected
                    </button>
                    <button
                      className="library-menu-item library-menu-item-danger"
                      onClick={openDeleteDialog}
                      disabled={selectedVideos.length === 0}
                    >
                      Delete selected
                    </button>
                  </>
                )}
              </div>
            ) : null}
          </div>
        </div>
      </header>

      {error && <div className="error">{error}</div>}
      {actionNotice && <div className="notice">{actionNotice}</div>}

      {tab === "all" && (
        <>
          {loading ? (
            <div className="status">Loading videos...</div>
          ) : videos.length === 0 ? (
            <div className="status">No videos found. Add media sources in Settings and run a scan.</div>
          ) : (
            <div className="video-group-list">
              {visibleGroupedVideos.map((group) => (
                <section key={group.key} className="video-group-section">
                  <button className="video-group-header video-group-toggle" onClick={() => toggleVideoGroup(group.key)}>
                    <span>{collapsedVideoGroups.has(group.key) ? ">" : "v"}</span>
                    <span>{group.title} - {group.videos.length} / {group.totalCount} videos</span>
                  </button>
                  {!collapsedVideoGroups.has(group.key) && (
                    <div className="video-grid video-grid-grouped">
                      {group.videos.map((video) => (
                        <VideoCard
                          key={video.id}
                          video={video}
                          selectionMode={selectionMode}
                          selected={selectedIds.has(video.id)}
                          onToggleSelect={toggleSelected}
                        />
                      ))}
                    </div>
                  )}
                </section>
              ))}
              <div className="library-load-more-row">
                <span className="library-load-more-count">Showing {totalVisibleVideos} of {videos.length}</span>
                {canLoadMoreVideos ? (
                  <button className="btn-secondary" onClick={loadMoreVideos}>Load more</button>
                ) : (
                  <span className="library-load-more-done">All videos loaded</span>
                )}
              </div>
            </div>
          )}
        </>
      )}

      {tab === "folders" && (
        <div className="folders-panel">
          {folderLoading ? (
            <div className="status">Loading folders...</div>
          ) : folderTrees.length === 0 ? (
            <div className="status">No folders found. Add media sources in Settings and run a scan.</div>
          ) : (
            folderTrees.map((source) => {
              const prefixedExpanded = new Set(
                [...expandedFolders]
                  .filter((entry) => entry.startsWith(`${source.key}::`))
                  .map((entry) => entry.slice(source.key.length + 2))
              );

              return (
                <section key={source.key} className="folder-source-section">
                  <h3 className="folder-source-title">{source.name}</h3>
                  <FolderTree
                    root={source.tree}
                    expandedPaths={prefixedExpanded}
                    onToggle={(path) => toggleFolder(`${source.key}::${path}`)}
                    progressByVideoId={{}}
                    sort={sort}
                    order={order}
                    selectionMode={selectionMode}
                    selectedVideoIds={selectedIds}
                    onToggleVideoSelect={toggleSelected}
                  />
                </section>
              );
            })
          )}
        </div>
      )}

      <TagSelectorDialog
        open={tagDialogOpen}
        title="Add tags to selected videos"
        subtitle={`${selectedVideos.length} video(s) selected`}
        confirmLabel="Apply tags"
        onClose={() => setTagDialogOpen(false)}
        onApply={handleBulkAssignTags}
      />

      {deleteDialogOpen ? (
        <div className="modal-overlay" onClick={bulkDeleteBusy ? undefined : closeDeleteDialog}>
          <div className="modal-box" onClick={(event) => event.stopPropagation()}>
            <div className="modal-header">
              <h3>Delete selected videos?</h3>
              <button className="modal-close" onClick={closeDeleteDialog} disabled={bulkDeleteBusy}>x</button>
            </div>

            <div className="modal-body">
              <p>
                Selected: <strong>{selectedVideos.length}</strong> video(s), total size <strong>{formatSize(selectedTotalSize)}</strong>
              </p>
              <p className="settings-error" style={{ marginTop: 8 }}>
                Original media files will be deleted. Generated HLS, thumbnails, and related records will also be removed. This cannot be undone.
              </p>

              <div className="modal-file-list-wrap">
                <ul className="modal-file-list">
                  {selectedVideos.map((video) => (
                    <li key={video.id}>
                      <span>
                        {video.title}
                        <br />
                        <small>{video.filename}</small>
                      </span>
                      <span>{formatSize(video.size)}</span>
                    </li>
                  ))}
                </ul>
              </div>

              {bulkDeleteBusy ? <div className="settings-loading">Deleting selected videos...</div> : null}

              {bulkDeleteResult ? (
                <div className="settings-notice">
                  Deleted: {bulkDeleteResult.deleted.length}. Failed: {bulkDeleteResult.failed.length}.
                  {bulkDeleteResult.failed.length > 0 ? (
                    <ul className="library-bulk-errors">
                      {bulkDeleteResult.failed.map((item) => (
                        <li key={`${item.video_id}-${item.error}`}>#{item.video_id}: {item.error}</li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              ) : null}
            </div>

            <div className="modal-footer">
              {bulkDeleteResult ? (
                <button className="btn-primary" onClick={closeDeleteDialog}>Close</button>
              ) : (
                <>
                  <button className="btn-secondary" onClick={closeDeleteDialog} disabled={bulkDeleteBusy}>Cancel</button>
                  <button className="btn-danger" onClick={() => void handleBulkDelete()} disabled={bulkDeleteBusy || selectedVideos.length === 0}>
                    {bulkDeleteBusy ? "Deleting..." : "Delete"}
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
