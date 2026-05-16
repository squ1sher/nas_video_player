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
  video_profile: string | null;
  video_level: string | null;
  pixel_format: string | null;
  audio_codec: string | null;
  audio_channels: number | null;
  audio_sample_rate: number | null;
  thumbnail_url: string | null;
  folder_path: string | null;
  compatibility_status: "direct_play" | "may_play" | "may_not_play" | "needs_conversion" | "unknown" | null;
  compatibility_reason: string | null;
  media_status: "detected_video" | "probe_failed_possible_video" | "ignored_non_media" | "ignored_excluded" | null;
  probe_status: "success" | "failed" | "skipped" | null;
  probe_error: string | null;
  container_format: string | null;
  thumbnail_status: "pending" | "generated" | "failed" | "skipped" | null;
  thumbnail_error: string | null;
  media_profile_id: number | null;
  media_profile_key: string | null;
  auto_compatibility_status: "direct_play" | "may_play" | "may_not_play" | "needs_conversion" | "unknown" | null;
  auto_compatibility_reason: string | null;
  effective_compatibility_status: "direct_play" | "may_play" | "may_not_play" | "needs_conversion" | "unknown" | null;
  compatibility_source: "manual_profile_override" | "manual_video_override" | "browser_probe" | "auto_heuristic" | "unknown" | null;
  manual_playback_status: "playable" | "not_playable" | "partially_playable" | "unknown" | null;
  file_modified_at: string | null;
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
  video_profile: string | null;
  video_level: string | null;
  pixel_format: string | null;
  audio_codec: string | null;
  audio_channels: number | null;
  audio_sample_rate: number | null;
  thumbnail_url: string | null;
  folder_path: string | null;
  compatibility_status: "direct_play" | "may_play" | "may_not_play" | "needs_conversion" | "unknown" | null;
  compatibility_reason: string | null;
  media_status: "detected_video" | "probe_failed_possible_video" | "ignored_non_media" | "ignored_excluded" | null;
  probe_status: "success" | "failed" | "skipped" | null;
  probe_error: string | null;
  container_format: string | null;
  thumbnail_status: "pending" | "generated" | "failed" | "skipped" | null;
  thumbnail_error: string | null;
  media_profile_id: number | null;
  media_profile_key: string | null;
  auto_compatibility_status: "direct_play" | "may_play" | "may_not_play" | "needs_conversion" | "unknown" | null;
  auto_compatibility_reason: string | null;
  effective_compatibility_status: "direct_play" | "may_play" | "may_not_play" | "needs_conversion" | "unknown" | null;
  compatibility_source: "manual_profile_override" | "manual_video_override" | "browser_probe" | "auto_heuristic" | "unknown" | null;
  manual_playback_status: "playable" | "not_playable" | "partially_playable" | "unknown" | null;
  file_modified_at: string | null;
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
  scanned_files: number;
  detected_videos: number;
  probe_failed: number;
  ignored_non_media: number;
  ignored_excluded: number;
  thumbnails_generated: number;
  thumbnail_errors: number;
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

export type LibraryLastScanSummary = {
  status: "idle" | "running" | "completed" | "failed";
  started_at: string | null;
  finished_at: string | null;
  scanned_files: number;
  detected_videos: number;
  probe_failed: number;
  ignored_non_media: number;
  ignored_excluded: number;
  thumbnail_errors: number;
};

export type LibraryLastDuplicateSummary = {
  status: "idle" | "running" | "completed" | "failed";
  candidate_groups_found: number;
  potential_saving: number;
  finished_at: string | null;
};

export type LibrarySummary = {
  total_indexed: number;
  detected_videos: number;
  probe_failed_possible_video: number;
  direct_play: number;
  may_play: number;
  may_not_play: number;
  needs_conversion: number;
  unknown_compatibility: number;
  thumbnail_generated: number;
  thumbnail_failed: number;
  thumbnail_missing: number;
  total_size: number;
  media_profiles_total: number;
  media_profiles_manual_checked: number;
  media_profiles_pending_manual_check: number;
  media_profiles_playable: number;
  media_profiles_not_playable: number;
  media_profiles_partially_playable: number;
  media_profiles_unknown: number;
  last_library_scan: LibraryLastScanSummary;
  last_duplicate_scan: LibraryLastDuplicateSummary;
};

export type ManualPlaybackStatus = "playable" | "not_playable" | "partially_playable" | "unknown";

export type MediaProfileSampleVideo = {
  id: number;
  title: string;
  filename: string;
  relative_path: string;
  thumbnail_url: string | null;
  watch_url: string;
};

export type MediaProfileItem = {
  id: number;
  profile_key: string;
  profile_version: string;
  files_count: number;
  sample_video: MediaProfileSampleVideo | null;
  extension: string;
  container_format: string;
  video_codec: string;
  video_profile: string;
  video_level: string;
  pixel_format: string;
  audio_codec: string;
  audio_channels: number | null;
  audio_sample_rate: number | null;
  width_bucket: string;
  height_bucket: string;
  auto_compatibility_status: "direct_play" | "may_play" | "may_not_play" | "needs_conversion" | "unknown";
  auto_compatibility_reason: string;
  manual_playback_status: ManualPlaybackStatus | null;
  manual_playback_note: string | null;
  manual_checked_at: string | null;
  effective_compatibility_status: "direct_play" | "may_play" | "may_not_play" | "needs_conversion" | "unknown";
  compatibility_source: "manual_profile_override" | "manual_video_override" | "browser_probe" | "auto_heuristic" | "unknown";
};

export type MediaProfileDetail = MediaProfileItem & {
  videos: VideoListItem[];
};

