export type VideoListItem = {
  id: number;
  title: string;
  filename: string;
  extension: string;
  size: number;
  duration: number | null;
  width: number | null;
  height: number | null;
  video_codec: string | null;
  audio_codec: string | null;
  thumbnail_url: string | null;
  folder_path: string | null;
  compatibility_status: "direct_play" | "may_not_play" | "needs_conversion" | null;
  compatibility_reason: string | null;
  created_at: string;
  indexed_at: string;
};

export type VideoDetail = {
  id: number;
  title: string;
  filename: string;
  relative_path: string;
  extension: string;
  size: number;
  duration: number | null;
  width: number | null;
  height: number | null;
  video_codec: string | null;
  audio_codec: string | null;
  thumbnail_url: string | null;
  folder_path: string | null;
  compatibility_status: "direct_play" | "may_not_play" | "needs_conversion" | null;
  compatibility_reason: string | null;
  created_at: string;
  updated_at: string;
  indexed_at: string;
};

export type WatchProgress = {
  video_id: number;
  position_seconds: number;
  duration_seconds: number;
  percent_watched: number;
  completed: boolean;
  last_watched_at: string | null;
};

export type VideoWithProgress = VideoListItem & {
  progress: WatchProgress;
};

export type ScanStatus = {
  status: "idle" | "running" | "completed" | "failed";
  started_at: string | null;
  finished_at: string | null;
  scanned: number;
  added: number;
  updated: number;
  errors: string[];
  current_file: string | null;
};

export type ScanStartedResponse = {
  status: string;
  message: string;
};

export type FolderInfo = {
  folder_path: string;
  video_count: number;
};
