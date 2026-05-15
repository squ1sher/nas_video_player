import { useEffect, useMemo, useState } from "react";
import { fetchVideos, runScan } from "../api/client";
import { SearchBar } from "../components/SearchBar";
import { SortSelect } from "../components/SortSelect";
import { VideoCard } from "../components/VideoCard";
import type { VideoListItem } from "../types/video";

type SortField = "title" | "created_at" | "duration" | "size";
type SortOrder = "asc" | "desc";

export function LibraryPage() {
  const [videos, setVideos] = useState<VideoListItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [scanMessage, setScanMessage] = useState<string | null>(null);
  const [search, setSearch] = useState<string>("");
  const [sort, setSort] = useState<SortField>("title");
  const [order, setOrder] = useState<SortOrder>("asc");

  const filteredSearch = useMemo(() => search.trim(), [search]);

  async function loadVideos() {
    try {
      setLoading(true);
      setError(null);
      const data = await fetchVideos({ q: filteredSearch, sort, order });
      setVideos(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load videos");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadVideos();
  }, [filteredSearch, sort, order]);

  async function onScanClick() {
    try {
      setScanMessage("Scanning in progress...");
      const result = await runScan();
      if (result.errors.length > 0) {
        setScanMessage(
          `Scan done. scanned=${result.scanned}, added=${result.added}, updated=${result.updated}, errors=${result.errors.length}`
        );
      } else {
        setScanMessage(`Scan done. scanned=${result.scanned}, added=${result.added}, updated=${result.updated}`);
      }
      await loadVideos();
    } catch (err) {
      setScanMessage(null);
      setError(err instanceof Error ? err.message : "Scan failed");
    }
  }

  return (
    <div className="page">
      <header className="page-header">
        <h1>Wochya Mini YouTube</h1>
        <button onClick={onScanClick}>Scan Library</button>
      </header>

      <div className="toolbar">
        <SearchBar value={search} onChange={setSearch} />
        <SortSelect sort={sort} order={order} onSortChange={setSort} onOrderChange={setOrder} />
      </div>

      {scanMessage && <div className="notice">{scanMessage}</div>}
      {error && <div className="error">{error}</div>}

      {loading ? (
        <div className="status">Loading videos...</div>
      ) : videos.length === 0 ? (
        <div className="status">Library is empty. Click Scan Library.</div>
      ) : (
        <section className="video-grid">
          {videos.map((video) => (
            <VideoCard key={video.id} video={video} />
          ))}
        </section>
      )}
    </div>
  );
}

