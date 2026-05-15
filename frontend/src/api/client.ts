import type { ScanResult, VideoDetail, VideoListItem } from "../types/video";

const API_BASE = "/api";

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Request failed with status ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function fetchVideos(params: {
  q?: string;
  sort?: "title" | "created_at" | "duration" | "size";
  order?: "asc" | "desc";
}): Promise<VideoListItem[]> {
  const query = new URLSearchParams();
  if (params.q) query.set("q", params.q);
  if (params.sort) query.set("sort", params.sort);
  if (params.order) query.set("order", params.order);

  const suffix = query.toString() ? `?${query}` : "";
  return handleResponse<VideoListItem[]>(await fetch(`${API_BASE}/videos${suffix}`));
}

export async function fetchVideo(id: string): Promise<VideoDetail> {
  return handleResponse<VideoDetail>(await fetch(`${API_BASE}/videos/${id}`));
}

export async function runScan(): Promise<ScanResult> {
  return handleResponse<ScanResult>(
    await fetch(`${API_BASE}/scan`, {
      method: "POST",
    })
  );
}

