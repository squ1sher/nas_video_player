import { useEffect, useMemo, useRef, useState } from "react";
import {
  fetchVideos,
  getContinueWatching,
  getFolders,
  getScanStatus,
  runScan,
} from "../api/client";
import type { SortField, SortOrder } from "../api/client";
import { ScanStatusBar } from "../components/ScanStatusBar";
import { SearchBar } from "../components/SearchBar";
import { SortSelect } from "../components/SortSelect";
import { VideoCard } from "../components/VideoCard";
import type { FolderInfo, ScanStatus, VideoListItem, VideoWithProgress } from "../types/video";

type Tab = "all" | "folders" | "continue";

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
    if (existing) {
      return existing;
    }
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
    for (const node of nodes) {
      sortTree(node.children);
    }
  };

  sortTree(root.children);
  return root.children;
}

export function LibraryPage() {
  const [tab, setTab] = useState<Tab>("all");
  const [videos, setVideos] = useState<VideoListItem[]>([]);
  const [continueWatching, setContinueWatching] = useState<VideoWithProgress[]>([]);
  const [folders, setFolders] = useState<FolderInfo[]>([]);
  const [selectedFolder, setSelectedFolder] = useState<string | null>(null);
  const [scanStatus, setScanStatus] = useState<ScanStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortField>("created_at");
  const [order, setOrder] = useState<SortOrder>("desc");
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set());
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const folderTree = useMemo(() => buildFolderTree(folders), [folders]);

  // ── scan status polling ──────────────────────────────────
  const startPolling = () => {
    if (pollRef.current) return;
    pollRef.current = setInterval(async () => {
      try {
        const s = await getScanStatus();
        setScanStatus(s);
        if (s.status !== "running") {
          stopPolling();
          if (s.status === "completed") {
            await loadVideos();
            await loadContinueWatching();
          }
        }
      } catch {
        stopPolling();
      }
    }, 1200);
  };

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  useEffect(() => {
    return () => stopPolling();
  }, []);

  // ── data loaders ─────────────────────────────────────────
  async function loadVideos() {
    try {
      setLoading(true);
      setError(null);
      const q = search.trim() || undefined;
      const folder = selectedFolder !== null ? selectedFolder : undefined;
      const data = await fetchVideos({ q, folder, sort, order });
      setVideos(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load videos");
    } finally {
      setLoading(false);
    }
  }

  async function loadContinueWatching() {
    try {
      const data = await getContinueWatching();
      setContinueWatching(data);
    } catch {
      // Not critical
    }
  }

  async function loadFolders() {
    try {
      const data = await getFolders();
      setFolders(data);
    } catch {
      // Not critical
    }
  }

  useEffect(() => {
    void loadVideos();
  }, [search, sort, order, selectedFolder]);

  useEffect(() => {
    void loadContinueWatching();
    void loadFolders();
    getScanStatus()
      .then((status) => {
        setScanStatus(status);
        if (status.status === "running") {
          startPolling();
        }
      })
      .catch(() => {});
  }, []);

  // ── scan action ───────────────────────────────────────────
  async function onScanClick() {
    try {
      setError(null);
      await runScan();
      const s = await getScanStatus();
      setScanStatus(s);
      if (s.status === "running") startPolling();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Scan failed");
    }
  }

  // ── sort handler ──────────────────────────────────────────
  const handleSortChange = (newSort: SortField, newOrder: SortOrder) => {
    setSort(newSort);
    setOrder(newOrder);
  };

  // ── folder select ─────────────────────────────────────────
  const handleFolderSelect = (fp: string) => {
    setSelectedFolder(fp);
    setTab("all");
  };

  const handleShowAll = () => {
    setSelectedFolder(null);
    setTab("all");
  };

  const toggleFolder = (path: string) => {
    setExpandedFolders((prev) => {
      const next = new Set(prev);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      return next;
    });
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
          <ul className="folder-tree-children">
            {node.children.map((child) => renderFolderNode(child))}
          </ul>
        )}
      </li>
    );
  };

  // ── progress map for all-videos tab ──────────────────────
  const progressMap = Object.fromEntries(
    continueWatching.map((v) => [v.id, v.progress])
  );

  return (
    <div className="page">
      <header className="page-header">
        <h1>NAS Video Player</h1>
        <button onClick={onScanClick} disabled={scanStatus?.status === "running"}>
          {scanStatus?.status === "running" ? "Scanning…" : "Scan Library"}
        </button>
      </header>

      <ScanStatusBar status={scanStatus} />
      {error && <div className="error">{error}</div>}

      {/* ── Tab navigation ── */}
      <nav className="lib-tabs">
        <button
          className={tab === "all" ? "tab-btn active" : "tab-btn"}
          onClick={handleShowAll}
        >
          All Videos
        </button>
        <button
          className={tab === "folders" ? "tab-btn active" : "tab-btn"}
          onClick={() => setTab("folders")}
        >
          Folders
        </button>
        <button
          className={tab === "continue" ? "tab-btn active" : "tab-btn"}
          onClick={() => setTab("continue")}
        >
          Continue Watching
          {continueWatching.length > 0 && (
            <span className="tab-badge">{continueWatching.length}</span>
          )}
        </button>
      </nav>

      {/* ── ALL VIDEOS tab ── */}
      {tab === "all" && (
        <>
          {selectedFolder !== null && (
            <div className="folder-breadcrumb">
              <button className="link-btn" onClick={handleShowAll}>All Videos</button>
              {" / "}
              <strong>{selectedFolder || "Root"}</strong>
            </div>
          )}
          <div className="toolbar">
            <SearchBar value={search} onChange={setSearch} />
            <SortSelect sort={sort} order={order} onChange={handleSortChange} />
          </div>
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

      {/* ── FOLDERS tab ── */}
      {tab === "folders" && (
        <div className="folders-panel">
          {folders.length === 0 ? (
            <div className="status">No folders found. Scan your library first.</div>
          ) : (
            <>
              <button className="folder-item folder-root-item" onClick={() => handleFolderSelect("")}>
                <span className="folder-icon">📁</span>
                <span className="folder-name">Root</span>
                <span className="folder-count">
                  {folders.find((item) => item.folder_path === "")?.video_count ?? 0} videos
                </span>
              </button>
              <ul className="folder-tree-list">
                {folderTree.map((node) => renderFolderNode(node))}
              </ul>
            </>
          )}
        </div>
      )}

      {/* ── CONTINUE WATCHING tab ── */}
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
    </div>
  );
}
