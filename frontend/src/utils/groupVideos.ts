import type { SortField, SortOrder } from "../api/client";
import type { VideoListItem } from "../types/video";

export type VideoSortMode = {
  sort: SortField;
  order: SortOrder;
};

export type VideoGroupKey = string;

export type VideoGroup = {
  key: VideoGroupKey;
  title: string;
  videos: VideoListItem[];
};

type GroupEntry = VideoGroup & {
  rank: number;
};

const UNKNOWN_DATE_GROUP = "Unknown date";

const TITLE_CYRILLIC_ORDER = [
  "А",
  "Б",
  "В",
  "Г",
  "Д",
  "Е",
  "Ё",
  "Ж",
  "З",
  "И",
  "Й",
  "К",
  "Л",
  "М",
  "Н",
  "О",
  "П",
  "Р",
  "С",
  "Т",
  "У",
  "Ф",
  "Х",
  "Ц",
  "Ч",
  "Ш",
  "Щ",
  "Ъ",
  "Ы",
  "Ь",
  "Э",
  "Ю",
  "Я",
];

const GIB = 1024 * 1024 * 1024;

function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function getVideoDate(video: VideoListItem): Date | null {
  return parseDate(video.file_modified_at) ?? parseDate(video.indexed_at) ?? parseDate(video.created_at);
}

function createDateGroup(video: VideoListItem): GroupEntry {
  const date = getVideoDate(video);
  if (!date) {
    return {
      key: "date:unknown",
      title: UNKNOWN_DATE_GROUP,
      rank: Number.POSITIVE_INFINITY,
      videos: [video],
    };
  }

  const year = date.getFullYear();
  const month = date.getMonth();
  return {
    key: `date:${year}-${String(month + 1).padStart(2, "0")}`,
    title: date.toLocaleDateString("en-US", { month: "long", year: "numeric" }),
    rank: year * 12 + month,
    videos: [video],
  };
}

function createTitleGroup(video: VideoListItem): GroupEntry {
  const first = Array.from(video.title.trimStart())[0];
  if (!first) {
    return {
      key: "title:#",
      title: "#",
      rank: -1,
      videos: [video],
    };
  }

  const char = first.toLocaleUpperCase("ru-RU");
  if (/^[A-Z]$/.test(char)) {
    return {
      key: `title:latin:${char}`,
      title: char,
      rank: char.charCodeAt(0) - 64,
      videos: [video],
    };
  }

  if (/^[А-ЯЁ]$/u.test(char)) {
    const index = TITLE_CYRILLIC_ORDER.indexOf(char);
    return {
      key: `title:cyrillic:${char}`,
      title: char,
      rank: index >= 0 ? 100 + index : 1000,
      videos: [video],
    };
  }

  return {
    key: "title:#",
    title: "#",
    rank: -1,
    videos: [video],
  };
}

function createDurationGroup(video: VideoListItem): GroupEntry {
  const duration = video.duration ?? 0;
  if (duration <= 0) {
    return {
      key: "duration:unknown",
      title: "Unknown duration",
      rank: 4,
      videos: [video],
    };
  }
  if (duration < 3 * 60) {
    return {
      key: "duration:under3",
      title: "Under 3 minutes",
      rank: 1,
      videos: [video],
    };
  }
  if (duration <= 20 * 60) {
    return {
      key: "duration:3to20",
      title: "3-20 minutes",
      rank: 2,
      videos: [video],
    };
  }
  return {
    key: "duration:over20",
    title: "Over 20 minutes",
    rank: 3,
    videos: [video],
  };
}

function createFileSizeGroup(video: VideoListItem): GroupEntry {
  const size = video.size ?? 0;
  if (size <= 0) {
    return {
      key: "size:unknown",
      title: "Unknown size",
      rank: 5,
      videos: [video],
    };
  }
  if (size < GIB) {
    return {
      key: "size:under1gib",
      title: "Under 1 GB",
      rank: 1,
      videos: [video],
    };
  }
  if (size <= 20 * GIB) {
    return {
      key: "size:1to20gib",
      title: "1-20 GB",
      rank: 2,
      videos: [video],
    };
  }
  if (size <= 100 * GIB) {
    return {
      key: "size:20to100gib",
      title: "20-100 GB",
      rank: 3,
      videos: [video],
    };
  }
  return {
    key: "size:over100gib",
    title: "Over 100 GB",
    rank: 4,
    videos: [video],
  };
}

function toGroupEntry(video: VideoListItem, sortMode: VideoSortMode): GroupEntry {
  if (sortMode.sort === "title") return createTitleGroup(video);
  if (sortMode.sort === "duration") return createDurationGroup(video);
  if (sortMode.sort === "size") return createFileSizeGroup(video);
  return createDateGroup(video);
}

export function sortVideoGroups(groups: GroupEntry[], sortMode: VideoSortMode): GroupEntry[] {
  const ordered = [...groups];
  if (sortMode.sort === "title") {
    ordered.sort((a, b) => {
      if (a.rank !== b.rank) return a.rank - b.rank;
      return a.title.localeCompare(b.title, "ru-RU");
    });
    if (sortMode.order === "desc") ordered.reverse();
    return ordered;
  }

  if (sortMode.sort === "duration" || sortMode.sort === "size") {
    ordered.sort((a, b) => a.rank - b.rank);
    if (sortMode.order === "desc") ordered.reverse();
    return ordered;
  }

  ordered.sort((a, b) => {
    const aUnknown = a.title === UNKNOWN_DATE_GROUP;
    const bUnknown = b.title === UNKNOWN_DATE_GROUP;
    if (aUnknown !== bUnknown) return aUnknown ? 1 : -1;
    return a.rank - b.rank;
  });
  const unknown = ordered.filter((group) => group.title === UNKNOWN_DATE_GROUP);
  const known = ordered.filter((group) => group.title !== UNKNOWN_DATE_GROUP);
  if (sortMode.order === "desc") known.reverse();
  return [...known, ...unknown];
}

export function groupVideos(videos: VideoListItem[], sortMode: VideoSortMode): VideoGroup[] {
  const groupsMap = new Map<VideoGroupKey, GroupEntry>();

  for (const video of videos) {
    const group = toGroupEntry(video, sortMode);
    const existing = groupsMap.get(group.key);
    if (!existing) {
      groupsMap.set(group.key, group);
      continue;
    }
    existing.videos.push(video);
  }

  return sortVideoGroups([...groupsMap.values()], sortMode).map(({ key, title, videos: groupedVideos }) => ({
    key,
    title,
    videos: groupedVideos,
  }));
}


