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

export type DuplicateMode = "strict";

export type DuplicateConfidence = "exact_metadata_match" | "high" | "medium";

export type DuplicateScanStatus = {
  status: "idle" | "running" | "completed" | "failed";
  mode: DuplicateMode;
  started_at: string | null;
  finished_at: string | null;
  videos_checked: number;
  candidate_groups_found: number;
  duplicate_candidates_found: number;
  current_step: string | null;
  errors: string[];
  last_result_summary: Record<string, string | number | null> | null;
};

export type DuplicateFingerprint = {
  mode: DuplicateMode;
  version: string;
  file_size: number;
  duration_seconds: number | null;
  width: number | null;
  height: number | null;
  video_codec: string | null;
  audio_codec: string | null;
  extension: string | null;
  normalized_title: string | null;
};

export type DuplicateGroupVideo = {
  id: number;
  title: string;
  filename: string;
  relative_path: string;
  size: number;
  duration: number | null;
  width: number | null;
  height: number | null;
  video_codec: string | null;
  audio_codec: string | null;
  extension: string;
  thumbnail_url: string | null;
  watch_url: string;
};

export type DuplicateGroup = {
  group_id: string;
  confidence: DuplicateConfidence;
  reason: string;
  candidate_count: number;
  total_size: number;
  potential_saving: number;
  fingerprint: DuplicateFingerprint;
  videos: DuplicateGroupVideo[];
};

export type DuplicateSummary = {
  last_scan_status: "idle" | "running" | "completed" | "failed";
  candidate_groups_found: number;
  duplicate_candidates_found: number;
  potential_saving: number;
  last_scan_at: string | null;
  mode: DuplicateMode;
};

