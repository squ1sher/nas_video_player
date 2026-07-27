import type { SortField, SortOrder } from "../api/client";
import type { UnifiedMediaItem } from "../types/video";

export type MediaGroup = {
  key: string;
  title: string;
  items: UnifiedMediaItem[];
};

type GroupEntry = MediaGroup & {
  rank: number;
};

const UNKNOWN_DATE_GROUP = "Unknown date";
const GIB = 1024 * 1024 * 1024;

function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function createDateGroup(item: UnifiedMediaItem): GroupEntry {
  const date = parseDate(item.date);
  if (!date) {
    return {
      key: "date:unknown",
      title: UNKNOWN_DATE_GROUP,
      rank: Number.POSITIVE_INFINITY,
      items: [item],
    };
  }

  const year = date.getFullYear();
  const month = date.getMonth();
  return {
    key: `date:${year}-${String(month + 1).padStart(2, "0")}`,
    title: date.toLocaleDateString("en-US", { month: "long", year: "numeric" }),
    rank: year * 12 + month,
    items: [item],
  };
}

function createTitleGroup(item: UnifiedMediaItem): GroupEntry {
  const first = Array.from(item.display_title.trimStart())[0];
  const title = first ? first.toLocaleUpperCase("en-US") : "#";
  const latin = /^[A-Z]$/.test(title);
  return {
    key: latin ? `title:${title}` : "title:#",
    title: latin ? title : "#",
    rank: latin ? title.charCodeAt(0) - 64 : -1,
    items: [item],
  };
}

function createDurationGroup(item: UnifiedMediaItem): GroupEntry {
  const duration = item.duration ?? 0;
  if (duration <= 0) {
    return {
      key: "duration:unknown",
      title: "Unknown duration",
      rank: 1,
      items: [item],
    };
  }
  if (duration < 3 * 60) {
    return {
      key: "duration:under3",
      title: "Under 3 minutes",
      rank: 2,
      items: [item],
    };
  }
  if (duration <= 20 * 60) {
    return {
      key: "duration:3to20",
      title: "3-20 minutes",
      rank: 3,
      items: [item],
    };
  }
  return {
    key: "duration:over20",
    title: "Over 20 minutes",
    rank: 4,
    items: [item],
  };
}

function createFileSizeGroup(item: UnifiedMediaItem): GroupEntry {
  const size = item.file_size ?? 0;
  if (size <= 0) {
    return {
      key: "size:unknown",
      title: "Unknown size",
      rank: 5,
      items: [item],
    };
  }
  if (size < GIB) {
    return {
      key: "size:under1gib",
      title: "Under 1 GB",
      rank: 1,
      items: [item],
    };
  }
  if (size <= 20 * GIB) {
    return {
      key: "size:1to20gib",
      title: "1-20 GB",
      rank: 2,
      items: [item],
    };
  }
  if (size <= 100 * GIB) {
    return {
      key: "size:20to100gib",
      title: "20-100 GB",
      rank: 3,
      items: [item],
    };
  }
  return {
    key: "size:over100gib",
    title: "Over 100 GB",
    rank: 4,
    items: [item],
  };
}

function toGroupEntry(item: UnifiedMediaItem, sort: SortField): GroupEntry {
  if (sort === "title") return createTitleGroup(item);
  if (sort === "duration") return createDurationGroup(item);
  if (sort === "size") return createFileSizeGroup(item);
  return createDateGroup(item);
}

function sortGroups(groups: GroupEntry[], sort: SortField, order: SortOrder): GroupEntry[] {
  const ordered = [...groups];

  if (sort === "title" || sort === "duration" || sort === "size") {
    ordered.sort((a, b) => a.rank - b.rank || a.title.localeCompare(b.title, "en-US"));
    if (order === "desc") ordered.reverse();
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
  if (order === "desc") known.reverse();
  return [...known, ...unknown];
}

export function groupMediaItems(items: UnifiedMediaItem[], options: { sort: SortField; order: SortOrder }): MediaGroup[] {
  const groupsMap = new Map<string, GroupEntry>();

  for (const item of items) {
    const group = toGroupEntry(item, options.sort);
    const existing = groupsMap.get(group.key);
    if (!existing) {
      groupsMap.set(group.key, group);
      continue;
    }
    existing.items.push(item);
  }

  return sortGroups([...groupsMap.values()], options.sort, options.order).map(({ key, title, items: groupedItems }) => ({
    key,
    title,
    items: groupedItems,
  }));
}
