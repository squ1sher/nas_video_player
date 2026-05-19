import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { fetchVideos } from "../api/client";
import type { SortField, SortOrder } from "../api/client";
import { SearchBar } from "../components/SearchBar";
import { SortSelect } from "../components/SortSelect";
import { VideoCard } from "../components/VideoCard";
import { FolderTree } from "../components/folders/FolderTree";
import type { VideoListItem } from "../types/video";
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

export function LibraryPage() {
  const navigate = useNavigate();
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
          <button className="btn-secondary" onClick={() => navigate("/settings")}>Settings</button>
        </div>
      </header>

      {error && <div className="error">{error}</div>}

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
                        <VideoCard key={video.id} video={video} />
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
                  />
                </section>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
