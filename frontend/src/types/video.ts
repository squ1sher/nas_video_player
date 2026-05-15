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
  created_at: string;
  updated_at: string;
  indexed_at: string;
};

export type ScanResult = {
  scanned: number;
  added: number;
  updated: number;
  errors: string[];
};

