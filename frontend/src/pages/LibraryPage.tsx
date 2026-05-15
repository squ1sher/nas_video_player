import { useEffect, useRef, useState } from "react";
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
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

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
    }, 3000);
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
      .then(setScanStatus)
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
            <ul className="folder-list">
              {folders.map((f) => (
                <li key={f.folder_path}>
                  <button
                    className="folder-item"
                    onClick={() => handleFolderSelect(f.folder_path)}
                  >
                    <span className="folder-icon">📁</span>
                    <span className="folder-name">{f.folder_path || "Root"}</span>
                    <span className="folder-count">{f.video_count} videos</span>
                  </button>
                </li>
              ))}
            </ul>
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
