import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import {
  bulkAssignTags,
  bulkDeleteVideos,
  bulkRemovePlaylistItems,
  deletePlaylist,
  getPlaylist,
  reorderPlaylistByVideoIds,
  updatePlaylist,
} from "../api/client";
import type { SortField, SortOrder } from "../api/client";
import { GroupCheckbox } from "../components/GroupCheckbox";
import { SearchBar } from "../components/SearchBar";
import { VideoCard } from "../components/VideoCard";
import { TagFilterDialog } from "../components/tags/TagFilterDialog";
import type { TagFilterState } from "../components/tags/TagFilterDialog";
import { TagSelectorDialog } from "../components/tags/TagSelectorDialog";
import type {
  PlaylistContextItem,
  PlaylistDetail,
  PlaylistItem,
  StoredPlaylistNav,
  VideoBulkDeleteResult,
  VideoListItem,
} from "../types/video";
import { groupVideos } from "../utils/groupVideos";

// ─── Constants ───────────────────────────────────────────────────────────────

const INITIAL_ITEMS = 60;
const LOAD_MORE_ITEMS = 60;
const MAX_ACTIVE_TAG_CHIPS = 3;

// ─── Playlist sort ────────────────────────────────────────────────────────────

type PlaylistSortField = "playlist_order" | SortField;

const PLAYLIST_SORT_OPTIONS: Array<{ label: string; value: PlaylistSortField }> = [
  { label: "Playlist order", value: "playlist_order" },
  { label: "Date", value: "file_modified_at" },
  { label: "Duration", value: "duration" },
  { label: "File size", value: "size" },
];

// ─── Helpers ─────────────────────────────────────────────────────────────────

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

function parseSortableDate(value: string | null | undefined): number | null {
  if (!value) return null;
  const parsed = new Date(value).getTime();
  return Number.isNaN(parsed) ? null : parsed;
}

function getPlaylistBrowseDate(video: VideoListItem): number | null {
  return parseSortableDate(video.file_modified_at) ?? parseSortableDate(video.indexed_at) ?? parseSortableDate(video.created_at);
}

/** Map a PlaylistItem to the VideoListItem shape consumed by VideoCard / groupVideos. */
function toVideoListItem(item: PlaylistItem): VideoListItem {
  const v = item.video as PlaylistItem["video"] & {
    size?: number;
    filename?: string;
    folder_path?: string | null;
    library_root_id?: number | null;
    library_root_name?: string | null;
    file_modified_at?: string | null;
    created_at?: string | null;
    indexed_at?: string | null;
  };
  return {
    id: item.id,
    library_root_id: v.library_root_id ?? null,
    library_root_name: v.library_root_name ?? null,
    title: v.display_title,
    filename: v.filename ?? "",
    extension: "",
    size: v.size ?? 0,
    duration: v.duration,
    width: null,
    height: null,
    video_codec: null,
    video_profile: null,
    video_level: null,
    pixel_format: null,
    audio_codec: null,
    audio_channels: null,
    audio_sample_rate: null,
    thumbnail_url: v.thumbnail_url,
    folder_path: v.folder_path ?? null,
    compatibility_status: null,
    compatibility_reason: null,
    media_status: null,
    probe_status: null,
    probe_error: null,
    container_format: null,
    thumbnail_status: null,
    thumbnail_error: null,
    media_profile_id: null,
    media_profile_key: null,
    auto_compatibility_status: null,
    auto_compatibility_reason: null,
    effective_compatibility_status: null,
    compatibility_source: null,
    manual_playback_status: null,
    file_modified_at: v.file_modified_at ?? null,
    created_at: v.created_at ?? new Date(0).toISOString(),
    indexed_at: v.indexed_at ?? new Date(0).toISOString(),
    tags: v.tags,
  };
}

// ─── Component ───────────────────────────────────────────────────────────────

export function PlaylistDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const playlistId = id ? parseInt(id, 10) : NaN;

  const menuRef = useRef<HTMLDivElement | null>(null);

  // ── Data ──────────────────────────────────────────────────────────────────
  const [playlist, setPlaylist] = useState<PlaylistDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionNotice, setActionNotice] = useState<string | null>(null);
  const [actionBusy, setActionBusy] = useState(false);

  // ── Controls ──────────────────────────────────────────────────────────────
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<PlaylistSortField>("playlist_order");
  const [order, setOrder] = useState<SortOrder>("asc");
  const [visibleCount, setVisibleCount] = useState(INITIAL_ITEMS);
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
  const [menuOpen, setMenuOpen] = useState(false);

  // ── Tag filter ────────────────────────────────────────────────────────────
  const [tagFilter, setTagFilter] = useState<TagFilterState>({
    selectedTagIds: [],
    mode: "any",
    withoutTags: false,
  });
  const [tagPathById, setTagPathById] = useState<Map<number, string>>(new Map());
  const [tagFilterDialogOpen, setTagFilterDialogOpen] = useState(false);

  // ── Selection ─────────────────────────────────────────────────────────────
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [tagDialogOpen, setTagDialogOpen] = useState(false);

  // ── Bulk delete dialog ────────────────────────────────────────────────────
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [bulkDeleteBusy, setBulkDeleteBusy] = useState(false);
  const [bulkDeleteResult, setBulkDeleteResult] = useState<VideoBulkDeleteResult | null>(null);

  // ── Remove from playlist dialog ───────────────────────────────────────────
  const [removeDialogOpen, setRemoveDialogOpen] = useState(false);
  const [removeBusy, setRemoveBusy] = useState(false);

  // ── Edit playlist modal ───────────────────────────────────────────────────
  const [editorOpen, setEditorOpen] = useState(false);
  const [editorName, setEditorName] = useState("");
  const [editorDescription, setEditorDescription] = useState("");

  // ── Reorder mode ──────────────────────────────────────────────────────────
  const [reorderMode, setReorderMode] = useState(false);
  const [reorderBusy, setReorderBusy] = useState(false);
  // draft order kept as video_ids during reorder
  const [reorderIds, setReorderIds] = useState<number[]>([]);

  // ─── Load playlist ────────────────────────────────────────────────────────

  const loadPlaylist = async () => {
    if (Number.isNaN(playlistId)) return;
    setLoading(true);
    setError(null);
    try {
      const data = await getPlaylist(playlistId);
      setPlaylist(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load playlist.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadPlaylist();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playlistId]);

  // ─── Menu outside click ───────────────────────────────────────────────────

  useEffect(() => {
    const handler = (event: MouseEvent) => {
      if (!menuRef.current) return;
      if (menuRef.current.contains(event.target as Node)) return;
      setMenuOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // ─── Reset visible count on filter/sort change ────────────────────────────

  useEffect(() => {
    setVisibleCount(INITIAL_ITEMS);
  }, [search, sort, order, tagFilter]);

  // ─── Clear selection when filters change ──────────────────────────────────

  useEffect(() => {
    if (selectionMode) {
      setSelectedIds(new Set());
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, tagFilter]);

  // ─── All items as VideoListItem ───────────────────────────────────────────

  const allItems = useMemo<VideoListItem[]>(() => {
    if (!playlist) return [];
    return playlist.items.map(toVideoListItem);
  }, [playlist]);

  // ─── Client-side filtering ────────────────────────────────────────────────

  const filteredItems = useMemo(() => {
    let items = allItems;

    // search
    const q = search.trim().toLowerCase();
    if (q) {
      items = items.filter((v) => v.title.toLowerCase().includes(q));
    }

    // tag filter
    if (tagFilter.withoutTags) {
      items = items.filter((v) => v.tags.length === 0);
    } else if (tagFilter.selectedTagIds.length > 0) {
      const ids = new Set(tagFilter.selectedTagIds);
      if (tagFilter.mode === "all") {
        items = items.filter((v) => tagFilter.selectedTagIds.every((id) => v.tags.some((t) => t.id === id)));
      } else {
        items = items.filter((v) => v.tags.some((t) => ids.has(t.id)));
      }
    }

    return items;
  }, [allItems, search, tagFilter]);

  const sortedItems = useMemo(() => {
    if (sort === "playlist_order") {
      return filteredItems;
    }

    const indexed = filteredItems.map((video, index) => ({ video, index }));
    indexed.sort((a, b) => {
      const direction = order === "asc" ? 1 : -1;

      if (sort === "title") {
        const byTitle = a.video.title.localeCompare(b.video.title, "ru-RU", { sensitivity: "base" });
        if (byTitle !== 0) return byTitle * direction;
      } else if (sort === "duration") {
        const byDuration = (a.video.duration ?? -1) - (b.video.duration ?? -1);
        if (byDuration !== 0) return byDuration * direction;
      } else if (sort === "size") {
        const bySize = a.video.size - b.video.size;
        if (bySize !== 0) return bySize * direction;
      } else {
        const aDate = getPlaylistBrowseDate(a.video);
        const bDate = getPlaylistBrowseDate(b.video);
        if (aDate === null && bDate !== null) return 1;
        if (aDate !== null && bDate === null) return -1;
        if (aDate !== null && bDate !== null && aDate !== bDate) {
          return (aDate - bDate) * direction;
        }
      }

      return a.index - b.index;
    });

    return indexed.map((entry) => entry.video);
  }, [filteredItems, order, sort]);

  // ─── Grouping / sorting ───────────────────────────────────────────────────

  type VisibleGroup = { key: string; title: string; videos: VideoListItem[]; totalCount: number };

  const groupedItems = useMemo<VisibleGroup[]>(() => {
    if (sort === "playlist_order") {
      return [{ key: "playlist_order", title: "Playlist order", videos: sortedItems, totalCount: sortedItems.length }];
    }
    const groups = groupVideos(sortedItems, { sort: sort as SortField, order });
    return groups.map((g) => ({ key: g.key, title: g.title, videos: g.videos, totalCount: g.videos.length }));
  }, [sortedItems, sort, order]);

  const visibleGroups = useMemo<VisibleGroup[]>(() => {
    let remaining = visibleCount;
    const result: VisibleGroup[] = [];
    for (const group of groupedItems) {
      if (remaining <= 0) break;
      const visibleVideos = group.videos.slice(0, remaining);
      if (visibleVideos.length > 0) {
        result.push({ ...group, videos: visibleVideos });
        remaining -= visibleVideos.length;
      }
    }
    return result;
  }, [groupedItems, visibleCount]);

  const totalVisible = useMemo(() => visibleGroups.reduce((s, g) => s + g.videos.length, 0), [visibleGroups]);
  const canLoadMore = totalVisible < sortedItems.length;

  const visibleVideos = useMemo(() => visibleGroups.flatMap((g) => g.videos), [visibleGroups]);

  // ─── Selection helpers ────────────────────────────────────────────────────

  const selectedVideos = useMemo(() => {
    return visibleVideos.filter((v) => selectedIds.has(v.id));
  }, [visibleVideos, selectedIds]);

  const selectedTotalSize = useMemo(() => selectedVideos.reduce((s, v) => s + v.size, 0), [selectedVideos]);

  const hasActiveTagFilter = tagFilter.withoutTags || tagFilter.selectedTagIds.length > 0;

  const activeTagChipItems = useMemo(() => {
    if (tagFilter.withoutTags) return [{ id: -1, label: "Without tags" }];
    return tagFilter.selectedTagIds.map((id) => ({ id, label: tagPathById.get(id) || `Tag #${id}` }));
  }, [tagFilter, tagPathById]);

  const visibleTagChipItems = activeTagChipItems.slice(0, MAX_ACTIVE_TAG_CHIPS);
  const hiddenTagChipCount = Math.max(0, activeTagChipItems.length - visibleTagChipItems.length);

  // ─── Tag filter handlers ──────────────────────────────────────────────────

  const applyTagFilter = (nextFilter: TagFilterState, selectedTags: Array<{ id: number; path: string }>) => {
    setTagFilter(nextFilter);
    if (nextFilter.withoutTags || selectedTags.length === 0) {
      setTagPathById(new Map());
    } else {
      setTagPathById(new Map(selectedTags.map((t) => [t.id, t.path])));
    }
    clearSelectionAndExit();
  };

  const clearTagFilter = () => {
    setTagFilter({ selectedTagIds: [], mode: "any", withoutTags: false });
    setTagPathById(new Map());
    clearSelectionAndExit();
  };

  const removeTagChip = (tagId: number) => {
    if (tagFilter.withoutTags) { clearTagFilter(); return; }
    const nextIds = tagFilter.selectedTagIds.filter((id) => id !== tagId);
    setTagFilter((prev) => ({ ...prev, selectedTagIds: nextIds }));
    setTagPathById((prev) => { const next = new Map(prev); next.delete(tagId); return next; });
    clearSelectionAndExit();
  };

  // ─── Selection handlers ───────────────────────────────────────────────────

  const clearSelectionAndExit = () => {
    setSelectedIds(new Set());
    setSelectionMode(false);
  };

  const toggleSelected = (videoId: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(videoId)) next.delete(videoId); else next.add(videoId);
      return next;
    });
  };

  const toggleGroupVideoSelection = (videoIds: number[]) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      const allSelected = videoIds.every((id) => next.has(id));
      if (allSelected) videoIds.forEach((id) => next.delete(id));
      else videoIds.forEach((id) => next.add(id));
      return next;
    });
  };

  const openSelectionMode = () => {
    setSelectionMode(true);
    setMenuOpen(false);
    setActionNotice(null);
  };

  // ─── Load more ────────────────────────────────────────────────────────────

  const loadMoreVideos = () => { setVisibleCount((prev) => prev + LOAD_MORE_ITEMS); };

  // ─── Group toggle ─────────────────────────────────────────────────────────

  const toggleGroup = (key: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  };

  // ─── Sort ─────────────────────────────────────────────────────────────────

  const handleSortChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const nextSort = e.target.value as PlaylistSortField;
    setSort(nextSort);
    if (nextSort === "playlist_order") setOrder("asc");
  };

  const toggleOrder = () => {
    if (sort === "playlist_order") return; // no order toggle on playlist order
    setOrder((prev) => (prev === "desc" ? "asc" : "desc"));
  };

  // ─── Bulk tag assign ──────────────────────────────────────────────────────

  const handleBulkAssignTags = async (tagIds: number[]) => {
    const videoIds = selectedVideos.map((v) => v.id);
    if (videoIds.length === 0 || tagIds.length === 0) return;
    const result = await bulkAssignTags(videoIds, tagIds);
    await loadPlaylist();
    clearSelectionAndExit();
    setActionNotice(`Assigned ${result.tags_assigned} tag(s) to ${result.videos_processed} video(s).`);
  };

  // ─── Bulk delete files ────────────────────────────────────────────────────

  const openDeleteDialog = () => { setDeleteDialogOpen(true); setBulkDeleteResult(null); setMenuOpen(false); };

  const closeDeleteDialog = () => {
    setDeleteDialogOpen(false);
    const result = bulkDeleteResult;
    setBulkDeleteResult(null);
    if (result) {
      clearSelectionAndExit();
      void loadPlaylist();
    }
  };

  const handleBulkDelete = async () => {
    const ids = selectedVideos.map((v) => v.id);
    if (ids.length === 0) return;
    setBulkDeleteBusy(true);
    try {
      const result = await bulkDeleteVideos(ids);
      setBulkDeleteResult(result);
      if (result.deleted.length > 0) {
        // playlist will be refreshed on dialog close
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

  // ─── Remove from playlist ─────────────────────────────────────────────────

  const openRemoveDialog = () => { setRemoveDialogOpen(true); setMenuOpen(false); };

  const closeRemoveDialog = () => { setRemoveDialogOpen(false); };

  const handleBulkRemoveFromPlaylist = async () => {
    const ids = selectedVideos.map((v) => v.id);
    if (ids.length === 0 || Number.isNaN(playlistId)) return;
    setRemoveBusy(true);
    try {
      const result = await bulkRemovePlaylistItems(playlistId, ids);
      setRemoveDialogOpen(false);
      clearSelectionAndExit();
      await loadPlaylist();
      setActionNotice(`Removed ${result.removed.length} video(s) from playlist.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to remove videos from playlist.");
    } finally {
      setRemoveBusy(false);
    }
  };

  // ─── Edit / delete playlist ───────────────────────────────────────────────

  const openEditPlaylist = () => {
    if (!playlist) return;
    setEditorName(playlist.name);
    setEditorDescription(playlist.description ?? "");
    setEditorOpen(true);
    setMenuOpen(false);
  };

  const submitEditor = async () => {
    if (!playlist || !editorName.trim()) return;
    setActionBusy(true);
    try {
      await updatePlaylist(playlist.id, { name: editorName.trim(), description: editorDescription.trim() || null });
      await loadPlaylist();
      setEditorOpen(false);
      setActionNotice("Playlist updated.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save playlist.");
    } finally {
      setActionBusy(false);
    }
  };

  const handleDeletePlaylist = async () => {
    if (!playlist) return;
    const ok = window.confirm("Delete playlist?\n\nVideos will not be deleted.");
    if (!ok) return;
    setActionBusy(true);
    try {
      await deletePlaylist(playlist.id);
      navigate("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete playlist.");
      setActionBusy(false);
    }
  };

  // ─── Reorder mode ────────────────────────────────────────────────────────

  const enterReorderMode = () => {
    if (!playlist) return;
    setReorderIds(playlist.items.map((item) => item.id));
    setReorderMode(true);
    setSelectionMode(false);
    setSelectedIds(new Set());
    setMenuOpen(false);
  };

  const cancelReorder = () => { setReorderMode(false); };

  const moveReorderItem = (videoId: number, direction: "up" | "down") => {
    setReorderIds((prev) => {
      const idx = prev.indexOf(videoId);
      if (idx < 0) return prev;
      const swapIdx = direction === "up" ? idx - 1 : idx + 1;
      if (swapIdx < 0 || swapIdx >= prev.length) return prev;
      const next = [...prev];
      const tmp = next[idx]; next[idx] = next[swapIdx]; next[swapIdx] = tmp;
      return next;
    });
  };

  const saveReorder = async () => {
    if (!playlist) return;
    setReorderBusy(true);
    try {
      const updated = await reorderPlaylistByVideoIds(playlist.id, reorderIds);
      setPlaylist(updated);
      setReorderMode(false);
      setActionNotice("Playlist order saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save reorder.");
    } finally {
      setReorderBusy(false);
    }
  };

  // ─── Reorder items (sorted by draft order) ────────────────────────────────

  const reorderItems = useMemo<PlaylistItem[]>(() => {
    if (!playlist) return [];
    const byId = new Map(playlist.items.map((item) => [item.id, item]));
    return reorderIds.map((id) => byId.get(id)).filter((i): i is PlaylistItem => !!i);
  }, [playlist, reorderIds]);

  // ─── Persist visual sort order so Watch page plays in same sequence ──────────

  useEffect(() => {
    if (Number.isNaN(playlistId) || !playlist) return;
    const key = `playlist_nav_${playlistId}`;
    const isCustomOrder = sort !== "playlist_order" || hasActiveTagFilter || !!search.trim();

    if (isCustomOrder && sortedItems.length > 0) {
      // Build availability lookup from raw playlist items
      const availByVideoId = new Map<number, string | null>(
        playlist.items.map((item) => [item.id, item.video.availability_status])
      );
      const sequence: PlaylistContextItem[] = sortedItems.map((video, idx) => ({
        video_id: video.id,
        position: idx + 1,
        display_title: video.title,
        thumbnail_url: video.thumbnail_url,
        availability_status: availByVideoId.get(video.id) ?? null,
      }));
      const nav: StoredPlaylistNav = {
        playlist_id: playlistId,
        playlist_name: playlist.name,
        sequence,
        timestamp: Date.now(),
      };
      try {
        sessionStorage.setItem(key, JSON.stringify(nav));
      } catch {
        // ignore storage failures
      }
    } else {
      // Default playlist order — let Watch page use backend context (manual position).
      try {
        sessionStorage.removeItem(key);
      } catch {
        // ignore
      }
    }
  }, [playlistId, sort, hasActiveTagFilter, search, sortedItems, playlist]);

  // ─── Render ───────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="page page-library-compact">
        <div className="status">Loading playlist...</div>
      </div>
    );
  }

  if (!playlist || Number.isNaN(playlistId)) {
    return (
      <div className="page page-library-compact">
        <div className="error">{error || "Playlist not found."}</div>
        <button className="btn-secondary" onClick={() => navigate("/")}>Back to Library</button>
      </div>
    );
  }

  return (
    <div className="page page-library-compact">
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <header className="library-compact-header">
        <button className="btn-secondary" onClick={() => navigate("/")}>
          ← Playlists
        </button>
        <div className="library-title-mini" style={{ flex: 1 }}>
          {playlist.name}
          <span className="playlist-header-count"> · {playlist.item_count} video{playlist.item_count !== 1 ? "s" : ""}</span>
        </div>

        {/* Controls */}
        {!reorderMode ? (
          <div className="library-controls-compact">
            <SearchBar value={search} onChange={setSearch} />

            <div className="sort-controls">
              <select value={sort} onChange={handleSortChange}>
                {PLAYLIST_SORT_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
              {sort !== "playlist_order" ? (
                <button type="button" className="sort-order-toggle" onClick={toggleOrder}>
                  {order === "desc" ? "Descending" : "Ascending"}
                </button>
              ) : null}
            </div>

            {selectionMode ? <span className="library-selected-count">Selected: {selectedVideos.length}</span> : null}

            <div className="library-menu" ref={menuRef}>
              <button className="btn-secondary" onClick={() => setMenuOpen((prev) => !prev)}>Menu</button>
              {menuOpen ? (
                <div className="library-menu-dropdown">
                  <button className="library-menu-item" onClick={() => navigate("/settings")}>Settings</button>
                  <button className="library-menu-item" onClick={openEditPlaylist} disabled={actionBusy}>Edit playlist</button>
                  <button className="library-menu-item library-menu-item-danger" onClick={() => void handleDeletePlaylist()} disabled={actionBusy}>Delete playlist</button>
                  <button className="library-menu-item" onClick={enterReorderMode}>Reorder playlist</button>
                  {hasActiveTagFilter ? (
                    <>
                      <button className="library-menu-item" onClick={() => { setTagFilterDialogOpen(true); setMenuOpen(false); }}>Edit tag filter</button>
                      <button className="library-menu-item" onClick={() => { clearTagFilter(); setMenuOpen(false); }}>Clear tag filter</button>
                    </>
                  ) : (
                    <button className="library-menu-item" onClick={() => { setTagFilterDialogOpen(true); setMenuOpen(false); }}>Filter by tags</button>
                  )}
                  {!selectionMode ? (
                    <button className="library-menu-item" onClick={openSelectionMode}>Select</button>
                  ) : (
                    <>
                      <button className="library-menu-item" onClick={() => { clearSelectionAndExit(); setMenuOpen(false); }}>Exit selection</button>
                      <button className="library-menu-item" onClick={() => { setTagDialogOpen(true); setMenuOpen(false); }} disabled={selectedVideos.length === 0}>Add tag to selected</button>
                      <button className="library-menu-item library-menu-item-danger" onClick={openRemoveDialog} disabled={selectedVideos.length === 0}>Remove from playlist</button>
                      <button className="library-menu-item library-menu-item-danger" onClick={openDeleteDialog} disabled={selectedVideos.length === 0}>Delete video files</button>
                    </>
                  )}
                </div>
              ) : null}
            </div>
          </div>
        ) : (
          /* Reorder mode controls */
          <div className="library-controls-compact">
            <span className="library-selected-count">Reorder mode</span>
            <button className="btn-secondary" onClick={cancelReorder} disabled={reorderBusy}>Cancel</button>
            <button className="btn-primary" onClick={() => void saveReorder()} disabled={reorderBusy}>
              {reorderBusy ? "Saving…" : "Save order"}
            </button>
          </div>
        )}
      </header>

      {/* Show note only when visual order differs from playlist order */}
      {(sort !== "playlist_order" || search.trim() || hasActiveTagFilter) && !reorderMode ? (
        <div className="playlist-browse-note">
          Playback uses playlist order. Sorting/filtering only changes this view.
        </div>
      ) : null}

      {/* ── Active tag filter chips ─────────────────────────────────────── */}
      {hasActiveTagFilter && !reorderMode ? (
        <div className="library-active-filter-row">
          {visibleTagChipItems.map((chip) => (
            <button key={chip.id} className="library-active-filter-chip" onClick={() => removeTagChip(chip.id)} title={`Remove filter: ${chip.label}`}>
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

      {error ? <div className="error">{error}</div> : null}
      {actionNotice ? <div className="notice">{actionNotice}</div> : null}

      {/* ── Reorder mode ──────────────────────────────────────────────────── */}
      {reorderMode ? (
        <div className="playlist-item-list">
          <p className="playlist-muted" style={{ padding: "8px 12px" }}>
            Use Up / Down to change playback order, then Save.
          </p>
          {reorderItems.map((item, index) => (
            <article key={item.playlist_item_id} className="playlist-item-row">
              <div className="playlist-item-order">{index + 1}</div>
              <div className="playlist-item-thumb">
                {item.video.thumbnail_url ? (
                  <img src={item.video.thumbnail_url} alt={item.video.display_title} loading="lazy" decoding="async" />
                ) : (
                  <div className="thumb placeholder">No Thumbnail</div>
                )}
              </div>
              <div className="playlist-item-main">
                <span className="playlist-item-title">{item.video.display_title}</span>
              </div>
              <div className="playlist-item-actions">
                <button className="btn-secondary" onClick={() => moveReorderItem(item.id, "up")} disabled={index === 0 || reorderBusy}>Up</button>
                <button className="btn-secondary" onClick={() => moveReorderItem(item.id, "down")} disabled={index === reorderItems.length - 1 || reorderBusy}>Down</button>
              </div>
            </article>
          ))}
        </div>
      ) : null}

      {/* ── Normal gallery view ────────────────────────────────────────────── */}
      {!reorderMode ? (
        <>
          {filteredItems.length === 0 ? (
            <div className="status">
              {playlist.item_count === 0
                ? "Playlist is empty."
                : hasActiveTagFilter || search.trim()
                  ? "No videos match the current filters."
                  : "No videos found."}
            </div>
          ) : (
            <div className="video-group-list">
              {visibleGroups.map((group) => {
                const groupVideoIds = group.videos.map((v) => v.id);
                const selectedInGroupCount = selectionMode
                  ? groupVideoIds.filter((id) => selectedIds.has(id)).length
                  : 0;
                const groupChecked =
                  selectedInGroupCount > 0 && selectedInGroupCount === groupVideoIds.length;
                const groupIndeterminate =
                  selectedInGroupCount > 0 && selectedInGroupCount < groupVideoIds.length;

                return (
                  <section key={group.key} className="video-group-section">
                    {/* Show group header only when there are multiple groups */}
                    {groupedItems.length > 1 ? (
                      <div className="video-group-header">
                        {selectionMode ? (
                          <GroupCheckbox
                            checked={groupChecked}
                            indeterminate={groupIndeterminate}
                            disabled={groupVideoIds.length === 0}
                            onChange={() => toggleGroupVideoSelection(groupVideoIds)}
                            label={`Select all loaded items in ${group.title}`}
                          />
                        ) : null}
                        <button
                          className="video-group-toggle"
                          onClick={() => toggleGroup(group.key)}
                        >
                          <span>{collapsedGroups.has(group.key) ? "▶" : "▼"}</span>
                          <span>
                            {group.title} – {group.videos.length} / {group.totalCount} videos
                            {selectionMode && selectedInGroupCount > 0 ? (
                              <span className="video-group-select-count">
                                {" "}· {selectedInGroupCount} / {groupVideoIds.length} selected
                              </span>
                            ) : null}
                          </span>
                        </button>
                      </div>
                    ) : null}
                    {!collapsedGroups.has(group.key) ? (
                      <div className="video-grid video-grid-grouped">
                        {group.videos.map((video) => (
                          <VideoCard
                            key={video.id}
                            video={video}
                            playlistId={playlistId}
                            selectionMode={selectionMode}
                            selected={selectedIds.has(video.id)}
                            onToggleSelect={toggleSelected}
                          />
                        ))}
                      </div>
                    ) : null}
                  </section>
                );
              })}

              <div className="library-load-more-row">
                <span className="library-load-more-count">Showing {totalVisible} of {filteredItems.length}</span>
                {canLoadMore ? (
                  <button className="btn-secondary" onClick={loadMoreVideos}>Load more</button>
                ) : (
                  <span className="library-load-more-done">All videos loaded</span>
                )}
              </div>
            </div>
          )}
        </>
      ) : null}

      {/* ── Dialogs ───────────────────────────────────────────────────────── */}

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

      {/* Edit playlist modal */}
      {editorOpen ? (
        <div className="modal-overlay" onClick={actionBusy ? undefined : () => setEditorOpen(false)}>
          <div className="modal-box" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Edit playlist</h3>
              <button className="modal-close" onClick={() => setEditorOpen(false)} disabled={actionBusy}>x</button>
            </div>
            <div className="modal-body playlist-new-form">
              <input
                placeholder="Playlist name"
                value={editorName}
                onChange={(e) => setEditorName(e.target.value)}
                disabled={actionBusy}
              />
              <textarea
                placeholder="Description (optional)"
                value={editorDescription}
                onChange={(e) => setEditorDescription(e.target.value)}
                disabled={actionBusy}
                rows={4}
              />
            </div>
            <div className="modal-footer">
              <button className="btn-secondary" onClick={() => setEditorOpen(false)} disabled={actionBusy}>Cancel</button>
              <button className="btn-primary" onClick={() => void submitEditor()} disabled={actionBusy || !editorName.trim()}>
                {actionBusy ? "Saving…" : "Save"}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {/* Remove from playlist confirmation */}
      {removeDialogOpen ? (
        <div className="modal-overlay" onClick={removeBusy ? undefined : closeRemoveDialog}>
          <div className="modal-box" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Remove from playlist?</h3>
              <button className="modal-close" onClick={closeRemoveDialog} disabled={removeBusy}>x</button>
            </div>
            <div className="modal-body">
              <p>Remove <strong>{selectedVideos.length}</strong> selected video(s) from this playlist?</p>
              <p className="playlist-muted" style={{ marginTop: 8 }}>
                Videos will remain in the library. This only removes them from the playlist.
              </p>
            </div>
            <div className="modal-footer">
              <button className="btn-secondary" onClick={closeRemoveDialog} disabled={removeBusy}>Cancel</button>
              <button className="btn-danger" onClick={() => void handleBulkRemoveFromPlaylist()} disabled={removeBusy || selectedVideos.length === 0}>
                {removeBusy ? "Removing…" : "Remove from playlist"}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {/* Bulk delete files confirmation */}
      {deleteDialogOpen ? (
        <div className="modal-overlay" onClick={bulkDeleteBusy ? undefined : closeDeleteDialog}>
          <div className="modal-box" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Delete video files?</h3>
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
              {bulkDeleteBusy ? <div className="settings-loading">Deleting selected videos…</div> : null}
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
                    {bulkDeleteBusy ? "Deleting…" : "Delete video files"}
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

