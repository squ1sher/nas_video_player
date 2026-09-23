import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  bulkAssignTags,
  bulkDeleteVideos,
  createPlaylist,
  fetchMedia,
  fetchVideos,
  getPlaylists,
} from "../api/client";
import type { MediaGroupBy, SortField, SortOrder } from "../api/client";
import { SearchBar } from "../components/SearchBar";
import { SortSelect } from "../components/SortSelect";
import { CollectionJumpNav } from "../components/CollectionJumpNav";
import type { JumpNavItem } from "../components/CollectionJumpNav";
import { FolderTree } from "../components/folders/FolderTree";
import { PhotoFolderTree } from "../components/folders/PhotoFolderTree";
import { GroupedMediaBrowser } from "../components/media/GroupedMediaBrowser";
import { AddToPlaylistDialog } from "../components/playlists/AddToPlaylistDialog";
import { TagFilterDialog } from "../components/tags/TagFilterDialog";
import type { TagFilterState } from "../components/tags/TagFilterDialog";
import { TagSelectorDialog } from "../components/tags/TagSelectorDialog";
import type { PlaylistSummary, UnifiedMediaItem, VideoBulkDeleteResult, VideoListItem } from "../types/video";
import { buildMediaFolderTree } from "../utils/buildMediaFolderTree";
import { buildFolderTree } from "../utils/buildFolderTree";

type Tab = "all" | "folders" | "playlists";
type LibraryMode = "videos" | "photos" | "all";

type SourceGroup = {
  key: string;
  name: string;
  videos: VideoListItem[];
};

type MediaSourceGroup = {
  key: string;
  name: string;
  items: UnifiedMediaItem[];
};

const MAX_ACTIVE_TAG_CHIPS = 3;

function sourceLabel(video: VideoListItem): string {
  return video.library_root_name || "Unassigned source";
}

function sourceKey(video: VideoListItem): string {
  return `${video.library_root_id ?? "none"}:${sourceLabel(video)}`;
}

function mediaSourceLabel(item: UnifiedMediaItem): string {
  return item.media_source_name || "Unassigned source";
}

function mediaSourceKey(item: UnifiedMediaItem): string {
  return `${item.media_source_id ?? "none"}:${mediaSourceLabel(item)}`;
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

function mediaGroupByFromSort(sort: SortField): MediaGroupBy {
  if (sort === "size") return "file_size";
  if (sort === "duration") return "duration";
  return "date";
}

export function LibraryPage() {
  const navigate = useNavigate();
  const menuRef = useRef<HTMLDivElement | null>(null);
  const [mode, setMode] = useState<LibraryMode>("videos");
  const [tab, setTab] = useState<Tab>("all");
  const [mediaItems, setMediaItems] = useState<UnifiedMediaItem[]>([]);
  const [folderVideos, setFolderVideos] = useState<VideoListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [folderLoading, setFolderLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortField>("file_modified_at");
  const [order, setOrder] = useState<SortOrder>("desc");
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set());
  const [expandedPhotoFolders, setExpandedPhotoFolders] = useState<Set<string>>(new Set());
  const [menuOpen, setMenuOpen] = useState(false);
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [selectedMediaKeys, setSelectedMediaKeys] = useState<Set<string>>(new Set());
  const [loadedItemsByKey, setLoadedItemsByKey] = useState<Map<string, UnifiedMediaItem>>(new Map());
  const [browserJumpItems, setBrowserJumpItems] = useState<JumpNavItem[]>([]);
  const [browserCollapseSignal, setBrowserCollapseSignal] = useState(0);
  const [tagDialogOpen, setTagDialogOpen] = useState(false);
  const [tagFilterDialogOpen, setTagFilterDialogOpen] = useState(false);
  const [tagFilter, setTagFilter] = useState<TagFilterState>({ selectedTagIds: [], mode: "any", withoutTags: false });
  const [tagPathById, setTagPathById] = useState<Map<number, string>>(new Map());
  const [playlists, setPlaylists] = useState<PlaylistSummary[]>([]);
  const [playlistLoading, setPlaylistLoading] = useState(false);
  const [playlistActionBusy, setPlaylistActionBusy] = useState(false);
  const [playlistDialogOpen, setPlaylistDialogOpen] = useState(false);
  const [playlistEditorOpen, setPlaylistEditorOpen] = useState(false);
  const [playlistEditorName, setPlaylistEditorName] = useState("");
  const [playlistEditorDescription, setPlaylistEditorDescription] = useState("");
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [bulkDeleteBusy, setBulkDeleteBusy] = useState(false);
  const [bulkDeleteResult, setBulkDeleteResult] = useState<VideoBulkDeleteResult | null>(null);
  const [actionNotice, setActionNotice] = useState<string | null>(null);

  const hasActiveTagFilter = tagFilter.withoutTags || tagFilter.selectedTagIds.length > 0;

  const activeTagChipItems = useMemo(() => {
    if (tagFilter.withoutTags) {
      return [{ id: -1, label: "Without tags" }];
    }
    return tagFilter.selectedTagIds.map((id) => ({
      id,
      label: tagPathById.get(id) || `Tag #${id}`,
    }));
  }, [tagFilter.selectedTagIds, tagFilter.withoutTags, tagPathById]);

  const visibleTagChipItems = activeTagChipItems.slice(0, MAX_ACTIVE_TAG_CHIPS);
  const hiddenTagChipCount = Math.max(0, activeTagChipItems.length - visibleTagChipItems.length);

  const groupByForBrowser = mediaGroupByFromSort(sort);

  // Selected videos for bulk operations (delete / tag / add-to-playlist).
  // In folder view selection is tracked by numeric id; in grouped views it is
  // tracked by typed media key and resolved against loaded items.
  const selectedVideos = useMemo(() => {
    if (mode === "videos" && tab === "folders") {
      return folderVideos
        .filter((video) => selectedIds.has(video.id))
        .map((video) => ({
          id: video.id,
          title: video.title,
          filename: video.filename,
          size: video.size,
        }));
    }
    const result: Array<{ id: number; title: string; filename: string; size: number }> = [];
    for (const key of selectedMediaKeys) {
      if (!key.startsWith("video:")) continue;
      const item = loadedItemsByKey.get(key);
      if (!item) continue;
      result.push({
        id: item.id,
        title: item.display_title,
        filename: item.extension ? `${item.display_title}.${item.extension}` : item.display_title,
        size: item.file_size,
      });
    }
    return result;
  }, [mode, tab, folderVideos, selectedIds, selectedMediaKeys, loadedItemsByKey]);

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

  const photoFolderSourceGroups = useMemo<MediaSourceGroup[]>(() => {
    const map = new Map<string, MediaSourceGroup>();
    for (const item of mediaItems) {
      if (item.type !== "photo") continue;
      const key = mediaSourceKey(item);
      const existing = map.get(key);
      if (existing) {
        existing.items.push(item);
      } else {
        map.set(key, {
          key,
          name: mediaSourceLabel(item),
          items: [item],
        });
      }
    }
    return [...map.values()].sort((a, b) => a.name.localeCompare(b.name, "en", { sensitivity: "base" }));
  }, [mediaItems]);

  const photoFolderTrees = useMemo(() => {
    return photoFolderSourceGroups.map((group) => ({
      ...group,
      tree: buildMediaFolderTree(group.items),
    }));
  }, [photoFolderSourceGroups]);

  const folderJumpItems = useMemo<JumpNavItem[]>(
    () => folderTrees.map((source) => ({ id: `folder-source-${source.key}`, label: source.name })),
    [folderTrees]
  );

  const photoFolderJumpItems = useMemo<JumpNavItem[]>(
    () => photoFolderTrees.map((source) => ({ id: `folder-source-${source.key}`, label: source.name })),
    [photoFolderTrees]
  );

  const collapseAllFolders = () => setExpandedFolders(new Set());
  const collapseAllPhotoFolders = () => setExpandedPhotoFolders(new Set());

  const loadFolderVideos = async () => {
    const data = await fetchVideos({
      sort,
      order,
      tag_ids: tagFilter.withoutTags ? undefined : tagFilter.selectedTagIds,
      tag_mode: tagFilter.mode,
      without_tags: tagFilter.withoutTags,
    });
    setFolderVideos(data);
  };

  const loadPlaylists = async () => {
    const data = await getPlaylists();
    setPlaylists(data);
  };

  const loadMediaItems = async (nextMode: LibraryMode) => {
    const mediaType = nextMode === "videos" ? "video" : nextMode === "photos" ? "photo" : "all";
    const payload = await fetchMedia({
      type: mediaType,
      search: search.trim() || undefined,
      sort: sort === "size" ? "file_size" : "date",
      order,
    });
    setMediaItems(payload.items);
  };

  useEffect(() => {
    let isMounted = true;

    const run = async () => {
      try {
        setError(null);
        if (mode === "videos") {
          if (tab === "all") {
            // Grouped browser self-fetches summaries lazily.
            setLoading(false);
          } else if (tab === "folders") {
            setFolderLoading(true);
            await loadFolderVideos();
          } else {
            setPlaylistLoading(true);
            await loadPlaylists();
          }
        } else if (mode === "photos" && tab === "folders") {
          setLoading(true);
          await loadMediaItems(mode);
        } else {
          // Photos "all" and mixed "all" use the grouped browser.
          setLoading(false);
        }
      } catch (err) {
        if (!isMounted) return;
        setError(err instanceof Error ? err.message : "Failed to load library data");
      } finally {
        if (!isMounted) return;
        setLoading(false);
        setFolderLoading(false);
        setPlaylistLoading(false);
      }
    };

    void run();

    return () => {
      isMounted = false;
    };
  }, [mode, tab, search, sort, order, tagFilter]);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (!menuRef.current) return;
      if (menuRef.current.contains(event.target as Node)) return;
      setMenuOpen(false);
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // GroupedMediaBrowser jump-nav items only apply while it's mounted.
  useEffect(() => {
    setBrowserJumpItems([]);
  }, [mode, tab]);

  useEffect(() => {
    if (!selectionMode) return;
    if (!(mode === "videos" && tab === "folders")) return;
    const validIds = new Set(folderVideos.map((video) => video.id));
    setSelectedIds((prev) => {
      const next = new Set<number>();
      prev.forEach((id) => {
        if (validIds.has(id)) next.add(id);
      });
      return next;
    });
  }, [selectionMode, mode, tab, folderVideos]);

  useEffect(() => {
    if (tab !== "playlists" || true) return; // playlist detail now uses separate page
  }, [tab]);

  useEffect(() => {
    if (mode !== "videos") {
      setTab("all");
      setSelectedIds(new Set());       // clear video selection when leaving videos mode
    } else {
      setSelectedMediaKeys(new Set()); // clear media selection when entering videos mode
    }
  }, [mode]);

  const handleSortChange = (nextSort: SortField, nextOrder: SortOrder) => {
    setSort(nextSort);
    setOrder(nextOrder);
  };

  const toggleFolder = (path: string) => {
    setExpandedFolders((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  const togglePhotoFolder = (path: string) => {
    setExpandedPhotoFolders((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  const handleItemsLoaded = (items: UnifiedMediaItem[]) => {
    setLoadedItemsByKey((prev) => {
      const next = new Map(prev);
      for (const item of items) {
        next.set(`${item.type}:${item.id}`, item);
      }
      return next;
    });
  };

  // Reset lazy selection/loaded state whenever the filter context changes.
  useEffect(() => {
    setSelectedMediaKeys(new Set());
    setLoadedItemsByKey(new Map());
  }, [mode, tab, search, sort, order, tagFilter]);

  useEffect(() => {
    if (tab === "playlists" && selectionMode) {
      setSelectedIds(new Set());
      setSelectionMode(false);
    }
  }, [tab, selectionMode]);

  const clearSelectionAndExit = () => {
    setSelectedIds(new Set());
    setSelectedMediaKeys(new Set());
    setSelectionMode(false);
  };

  const applyTagFilter = (
    nextFilter: TagFilterState,
    selectedTags: Array<{ id: number; path: string }>
  ) => {
    setTagFilter(nextFilter);
    if (nextFilter.withoutTags || selectedTags.length === 0) {
      setTagPathById(new Map());
    } else {
      setTagPathById(new Map(selectedTags.map((tag) => [tag.id, tag.path])));
    }
    if (selectionMode) {
      clearSelectionAndExit();
    }
  };

  const clearTagFilter = () => {
    setTagFilter({ selectedTagIds: [], mode: "any", withoutTags: false });
    setTagPathById(new Map());
    if (selectionMode) {
      clearSelectionAndExit();
    }
  };

  const removeTagFilterChip = (tagId: number) => {
    if (tagFilter.withoutTags) {
      clearTagFilter();
      return;
    }
    const nextIds = tagFilter.selectedTagIds.filter((id) => id !== tagId);
    setTagFilter((prev) => ({ ...prev, selectedTagIds: nextIds }));
    setTagPathById((prev) => {
      const next = new Map(prev);
      next.delete(tagId);
      return next;
    });
    if (selectionMode) {
      clearSelectionAndExit();
    }
  };

  const toggleSelected = (videoId: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(videoId)) next.delete(videoId);
      else next.add(videoId);
      return next;
    });
  };

  // ── Typed key for unified media items (photos/all mode) ─────────────────────
  const getMediaItemKey = (item: UnifiedMediaItem): string => `${item.type}:${item.id}`;

  const toggleMediaItem = (key: string) => {
    setSelectedMediaKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  // ── Group-level selection toggles ────────────────────────────────────────────
  const toggleGroupMediaSelection = (itemKeys: string[]) => {
    setSelectedMediaKeys((prev) => {
      const next = new Set(prev);
      const allSelected = itemKeys.every((k) => next.has(k));
      if (allSelected) itemKeys.forEach((k) => next.delete(k));
      else itemKeys.forEach((k) => next.add(k));
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
        setFolderVideos((prev) => prev.filter((video) => !deleted.has(video.id)));
        setLoadedItemsByKey((prev) => {
          const next = new Map(prev);
          for (const id of deleted) next.delete(`video:${id}`);
          return next;
        });
        setSelectedMediaKeys((prev) => {
          const next = new Set(prev);
          for (const id of deleted) next.delete(`video:${id}`);
          return next;
        });
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
    if (mode === "videos" && tab === "folders") {
      await loadFolderVideos();
    }
    clearSelectionAndExit();
    setActionNotice(
      `Assigned ${result.tags_assigned} tag(s) to ${result.videos_processed} selected video(s).`
    );
  };

  const handleAddSelectedToPlaylist = async (message: string) => {
    await loadPlaylists();
    clearSelectionAndExit();
    setActionNotice(message);
  };

  const openCreatePlaylist = () => {
    setPlaylistEditorOpen(true);
    setPlaylistEditorName("");
    setPlaylistEditorDescription("");
    setMenuOpen(false);
  };

  const submitPlaylistEditor = async () => {
    if (!playlistEditorName.trim()) return;
    setPlaylistActionBusy(true);
    try {
      await createPlaylist({
        name: playlistEditorName.trim(),
        description: playlistEditorDescription.trim() || null,
      });
      await loadPlaylists();
      setPlaylistEditorOpen(false);
      setActionNotice("Playlist created.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save playlist.");
    } finally {
      setPlaylistActionBusy(false);
    }
  };

  const selectionLabel =
    mode === "videos"
      ? `Selected: ${selectedVideos.length}`
      : `Selected: ${selectedMediaKeys.size}`;

  const toggleTab = (value: Tab) => setTab((prev) => (prev === value ? "all" : value));

  return (
    <div className="page page-library-compact">
      <header className="library-compact-header">
        <nav className="lib-tabs lib-tabs-compact">
          <button className={mode === "videos" ? "tab-btn active" : "tab-btn"} onClick={() => setMode("videos")}>Videos</button>
          <button className={mode === "photos" ? "tab-btn active" : "tab-btn"} onClick={() => setMode("photos")}>Photos</button>
          <button className={mode === "all" ? "tab-btn active" : "tab-btn"} onClick={() => setMode("all")}>All</button>
        </nav>
        {mode === "videos" ? (
          <nav className="lib-subtabs" aria-label="View">
            <button className={tab === "folders" ? "lib-subtab-btn active" : "lib-subtab-btn"} onClick={() => toggleTab("folders")}>Folders</button>
            <button className={tab === "playlists" ? "lib-subtab-btn active" : "lib-subtab-btn"} onClick={() => toggleTab("playlists")}>Playlists</button>
          </nav>
        ) : mode === "photos" ? (
          <nav className="lib-subtabs" aria-label="View">
            <button className={tab === "folders" ? "lib-subtab-btn active" : "lib-subtab-btn"} onClick={() => toggleTab("folders")}>Folders</button>
          </nav>
        ) : null}
        <div className="library-controls-compact">
          {(mode !== "videos" || tab !== "playlists") ? <SearchBar value={search} onChange={setSearch} /> : null}
          {(mode !== "videos" || tab !== "playlists") ? <SortSelect sort={sort} order={order} onChange={handleSortChange} /> : null}
          {selectionMode ? <span className="library-selected-count">{selectionLabel}</span> : null}

          <div className="library-menu" ref={menuRef}>
            <button className="btn-secondary" onClick={() => setMenuOpen((prev) => !prev)}>Menu</button>
            {menuOpen ? (
              <div className="library-menu-dropdown">
                <button className="library-menu-item" onClick={() => navigate("/settings")}>Settings</button>
                {mode === "videos" && tab === "playlists" ? (
                  <button className="library-menu-item" onClick={openCreatePlaylist}>Create playlist</button>
                ) : null}
                {mode === "videos" && tab !== "playlists" ? (
                  hasActiveTagFilter ? (
                    <>
                      <button className="library-menu-item" onClick={() => { setTagFilterDialogOpen(true); setMenuOpen(false); }}>
                        Edit tag filter
                      </button>
                      <button className="library-menu-item" onClick={() => { clearTagFilter(); setMenuOpen(false); }}>
                        Clear tag filter
                      </button>
                    </>
                  ) : (
                    <button className="library-menu-item" onClick={() => { setTagFilterDialogOpen(true); setMenuOpen(false); }}>
                      Filter by tags
                    </button>
                  )
                ) : null}

                {!selectionMode && tab !== "playlists" ? (
                  <button className="library-menu-item" onClick={openSelectionMode}>Select</button>
                ) : selectionMode ? (
                  <>
                    <button className="library-menu-item" onClick={() => { clearSelectionAndExit(); setMenuOpen(false); }}>
                      Exit selection
                    </button>
                    {mode === "videos" ? (
                      <>
                        <button
                          className="library-menu-item"
                          onClick={() => { setTagDialogOpen(true); setMenuOpen(false); }}
                          disabled={selectedVideos.length === 0}
                        >
                          Add tag to selected
                        </button>
                        <button
                          className="library-menu-item"
                          onClick={() => { setPlaylistDialogOpen(true); setMenuOpen(false); }}
                          disabled={selectedVideos.length === 0}
                        >
                          Add to playlist
                        </button>
                        <button
                          className="library-menu-item library-menu-item-danger"
                          onClick={openDeleteDialog}
                          disabled={selectedVideos.length === 0}
                        >
                          Delete selected
                        </button>
                      </>
                    ) : (
                      <span className="library-menu-info">
                        {selectedMediaKeys.size > 0
                          ? `${selectedMediaKeys.size} item(s) selected`
                          : "Select items with checkboxes"}
                      </span>
                    )}
                  </>
                ) : null}
              </div>
            ) : null}
          </div>
        </div>
      </header>

      {mode === "videos" && hasActiveTagFilter && tab !== "playlists" ? (
        <div className="library-active-filter-row">
          {visibleTagChipItems.map((chip) => (
            <button
              key={chip.id}
              className="library-active-filter-chip"
              onClick={() => removeTagFilterChip(chip.id)}
              title={`Remove filter: ${chip.label}`}
            >
              {chip.label} x
            </button>
          ))}
          {hiddenTagChipCount > 0 ? <span className="library-active-filter-more">+{hiddenTagChipCount}</span> : null}
          {!tagFilter.withoutTags ? (
            <button className="library-active-filter-mode" onClick={() => setTagFilterDialogOpen(true)}>
              Mode: {tagFilter.mode === "all" ? "All" : "Any"}
            </button>
          ) : null}
          <button className="library-active-filter-clear" onClick={clearTagFilter}>Clear</button>
        </div>
      ) : null}

      {error && <div className="error">{error}</div>}
      {actionNotice && <div className="notice">{actionNotice}</div>}

      {mode === "videos" && tab === "all" && (
        <>
          <CollectionJumpNav items={browserJumpItems} onCollapseAll={() => setBrowserCollapseSignal((n) => n + 1)} />
          <GroupedMediaBrowser
            type="video"
            groupBy={groupByForBrowser}
            order={order}
            search={search}
            tagIds={tagFilter.withoutTags ? undefined : tagFilter.selectedTagIds}
            tagMode={tagFilter.mode}
            withoutTags={tagFilter.withoutTags}
            selectionMode={selectionMode}
            selectedKeys={selectedMediaKeys}
            onToggleItem={(item) => toggleMediaItem(getMediaItemKey(item))}
            onToggleGroupItems={(items) => toggleGroupMediaSelection(items.map(getMediaItemKey))}
            onItemsLoaded={handleItemsLoaded}
            onGroupsChange={setBrowserJumpItems}
            collapseAllSignal={browserCollapseSignal}
            emptyMessage={
              hasActiveTagFilter
                ? "No videos match the selected tag filters."
                : "No videos found. Add media sources in Settings and run a scan."
            }
          />
        </>
      )}

      {mode === "videos" && tab === "folders" && (
        <div className="folders-panel">
          <CollectionJumpNav items={folderJumpItems} onCollapseAll={collapseAllFolders} />
          {folderLoading ? (
            <div className="status">Loading folders...</div>
          ) : folderTrees.length === 0 ? (
            <div className="status">
              {hasActiveTagFilter
                ? "No videos match the selected tag filters."
                : "No folders found. Add media sources in Settings and run a scan."}
            </div>
          ) : (
            folderTrees.map((source) => {
              const prefixedExpanded = new Set(
                [...expandedFolders]
                  .filter((entry) => entry.startsWith(`${source.key}::`))
                  .map((entry) => entry.slice(source.key.length + 2))
              );

              return (
                <section key={source.key} id={`folder-source-${source.key}`} className="folder-source-section">
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

      {mode === "videos" && tab === "playlists" && (
        <div className="playlists-panel">
          {playlistLoading ? (
            <div className="status">Loading playlists...</div>
          ) : playlists.length === 0 ? (
            <div className="status">No playlists yet. Create your first playlist from Menu.</div>
          ) : (
            <div className="playlist-grid">
              {playlists.map((playlist) => (
                <button
                  key={playlist.id}
                  className="playlist-card"
                  onClick={() => navigate(`/playlist/${playlist.id}`)}
                >
                  <strong>{playlist.name}</strong>
                  {playlist.description ? <span>{playlist.description}</span> : <span className="playlist-muted">No description</span>}
                  <small>{playlist.item_count} item(s)</small>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {mode === "photos" && tab === "folders" && (
        <div className="folders-panel">
          <CollectionJumpNav items={photoFolderJumpItems} onCollapseAll={collapseAllPhotoFolders} />
          {loading ? (
            <div className="status">Loading folders...</div>
          ) : photoFolderTrees.length === 0 ? (
            <div className="status">No photo folders found. Add a Photo or Mixed source and run a scan.</div>
          ) : (
            photoFolderTrees.map((source) => {
              const prefixedExpanded = new Set(
                [...expandedPhotoFolders]
                  .filter((entry) => entry.startsWith(`${source.key}::`))
                  .map((entry) => entry.slice(source.key.length + 2))
              );

              return (
                <section key={source.key} id={`folder-source-${source.key}`} className="folder-source-section">
                  <h3 className="folder-source-title">{source.name}</h3>
                  <PhotoFolderTree
                    root={source.tree}
                    expandedPaths={prefixedExpanded}
                    onToggle={(path) => togglePhotoFolder(`${source.key}::${path}`)}
                    sort={sort}
                    order={order}
                    selectionMode={selectionMode}
                    selectedMediaKeys={selectedMediaKeys}
                    onToggleMediaSelect={(item) => toggleMediaItem(getMediaItemKey(item))}
                  />
                </section>
              );
            })
          )}
        </div>
      )}

      {(mode !== "videos" && !(mode === "photos" && tab === "folders")) && (
        <>
          <CollectionJumpNav items={browserJumpItems} onCollapseAll={() => setBrowserCollapseSignal((n) => n + 1)} />
          <GroupedMediaBrowser
            type={mode === "photos" ? "photo" : "all"}
            groupBy={groupByForBrowser}
            order={order}
            search={search}
            selectionMode={selectionMode}
            selectedKeys={selectedMediaKeys}
            onToggleItem={(item) => toggleMediaItem(getMediaItemKey(item))}
            onToggleGroupItems={(items) => toggleGroupMediaSelection(items.map(getMediaItemKey))}
            onItemsLoaded={handleItemsLoaded}
            onGroupsChange={setBrowserJumpItems}
            collapseAllSignal={browserCollapseSignal}
            emptyMessage={
              mode === "photos"
                ? "No photos found. Add a Photo or Mixed source and run a scan."
                : "No media found."
            }
          />
        </>
      )}

      <TagSelectorDialog
        open={tagDialogOpen}
        title="Add tags to selected videos"
        subtitle={`${selectedVideos.length} video(s) selected`}
        confirmLabel="Apply tags"
        onClose={() => setTagDialogOpen(false)}
        onApply={handleBulkAssignTags}
      />

      <TagFilterDialog
        open={tagFilterDialogOpen}
        initialState={tagFilter}
        onClose={() => setTagFilterDialogOpen(false)}
        onApply={applyTagFilter}
      />

      <AddToPlaylistDialog
        open={playlistDialogOpen}
        selectedCount={selectedVideos.length}
        selectedVideoIds={selectedVideos.map((video) => video.id)}
        playlists={playlists}
        onClose={() => setPlaylistDialogOpen(false)}
        onDone={(message) => void handleAddSelectedToPlaylist(message)}
      />

      {playlistEditorOpen ? (
        <div className="modal-overlay" onClick={playlistActionBusy ? undefined : () => setPlaylistEditorOpen(false)}>
          <div className="modal-box" onClick={(event) => event.stopPropagation()}>
            <div className="modal-header">
              <h3>Create playlist</h3>
              <button className="modal-close" onClick={() => setPlaylistEditorOpen(false)} disabled={playlistActionBusy}>x</button>
            </div>
            <div className="modal-body playlist-new-form">
              <input
                placeholder="Playlist name"
                value={playlistEditorName}
                onChange={(event) => setPlaylistEditorName(event.target.value)}
                disabled={playlistActionBusy}
              />
              <textarea
                placeholder="Description (optional)"
                value={playlistEditorDescription}
                onChange={(event) => setPlaylistEditorDescription(event.target.value)}
                disabled={playlistActionBusy}
                rows={4}
              />
            </div>
            <div className="modal-footer">
              <button className="btn-secondary" onClick={() => setPlaylistEditorOpen(false)} disabled={playlistActionBusy}>Cancel</button>
              <button className="btn-primary" onClick={() => void submitPlaylistEditor()} disabled={playlistActionBusy || !playlistEditorName.trim()}>
                {playlistActionBusy ? "Saving..." : "Save"}
              </button>
            </div>
          </div>
        </div>
      ) : null}

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
