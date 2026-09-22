import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  fetchMediaGroupItems,
  fetchMediaGroups,
  type MediaGroupBy,
  type MediaGroupFilters,
} from "../../api/client";
import type { SortOrder } from "../../api/client";
import type { MediaGroup, UnifiedMediaItem } from "../../types/video";
import { GroupCheckbox } from "../GroupCheckbox";
import { InfiniteScrollSentinel } from "./InfiniteScrollSentinel";
import { MediaCard, mediaItemKey } from "./MediaCard";

const PAGE_SIZE = 100;

type LeafItemState = {
  items: UnifiedMediaItem[];
  total: number;
  hasMore: boolean;
  loading: boolean;
};

type Props = {
  type: "video" | "photo" | "all";
  groupBy: MediaGroupBy;
  order: SortOrder;
  search?: string;
  tagIds?: number[];
  tagMode?: "any" | "all";
  withoutTags?: boolean;
  mediaSourceId?: number;
  folder?: string;
  playlistId?: number;
  selectionMode?: boolean;
  selectedKeys: Set<string>;
  onToggleItem: (item: UnifiedMediaItem) => void;
  onToggleGroupItems: (items: UnifiedMediaItem[]) => void;
  onItemsLoaded?: (items: UnifiedMediaItem[]) => void;
  emptyMessage?: string;
};

function isUnknownYear(group: MediaGroup): boolean {
  return group.group_key.endsWith(":unknown");
}

function parseYear(groupKey: string): number | undefined {
  const raw = groupKey.split(":")[2];
  const value = Number(raw);
  return Number.isNaN(value) ? undefined : value;
}

function parseMonth(groupKey: string): { year: number; month: number } | null {
  const raw = groupKey.split(":")[2]; // "2026-07"
  if (!raw) return null;
  const [y, m] = raw.split("-");
  const year = Number(y);
  const month = Number(m);
  if (Number.isNaN(year) || Number.isNaN(month)) return null;
  return { year, month };
}

function parseBucket(groupKey: string): string | undefined {
  return groupKey.split(":")[1];
}

export function GroupedMediaBrowser(props: Props) {
  const {
    type,
    groupBy,
    order,
    search,
    tagIds,
    tagMode,
    withoutTags,
    mediaSourceId,
    folder,
    playlistId,
    selectionMode = false,
    selectedKeys,
    onToggleItem,
    onToggleGroupItems,
    onItemsLoaded,
    emptyMessage = "No media found.",
  } = props;

  const baseFilters = useMemo<MediaGroupFilters>(
    () => ({
      type,
      group_by: groupBy,
      order,
      search: search?.trim() || undefined,
      tag_ids: tagIds && tagIds.length > 0 ? tagIds : undefined,
      tag_mode: tagMode,
      without_tags: withoutTags || undefined,
      media_source_id: mediaSourceId,
      folder,
      playlist_id: playlistId,
    }),
    [type, groupBy, order, search, tagIds, tagMode, withoutTags, mediaSourceId, folder, playlistId]
  );

  // Serialized key used to reset all lazy state when filters change.
  const filterKey = useMemo(() => JSON.stringify(baseFilters), [baseFilters]);

  const [topGroups, setTopGroups] = useState<MediaGroup[]>([]);
  const [topLoading, setTopLoading] = useState(true);
  const [topError, setTopError] = useState<string | null>(null);

  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [monthsByYear, setMonthsByYear] = useState<Map<string, MediaGroup[]>>(new Map());
  const [monthsLoading, setMonthsLoading] = useState<Set<string>>(new Set());
  const [itemsByGroup, setItemsByGroup] = useState<Map<string, LeafItemState>>(new Map());

  const onItemsLoadedRef = useRef(onItemsLoaded);
  onItemsLoadedRef.current = onItemsLoaded;

  // Load top-level group summaries whenever filters change.
  useEffect(() => {
    let mounted = true;
    setTopLoading(true);
    setTopError(null);
    setExpanded(new Set());
    setMonthsByYear(new Map());
    setMonthsLoading(new Set());
    setItemsByGroup(new Map());

    fetchMediaGroups(baseFilters)
      .then((groups) => {
        if (mounted) setTopGroups(groups);
      })
      .catch((err) => {
        if (mounted) setTopError(err instanceof Error ? err.message : "Failed to load groups");
      })
      .finally(() => {
        if (mounted) setTopLoading(false);
      });

    return () => {
      mounted = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterKey]);

  const loadMonths = useCallback(
    (yearGroupKey: string) => {
      const year = parseYear(yearGroupKey);
      if (year === undefined) return;
      setMonthsLoading((prev) => new Set(prev).add(yearGroupKey));
      fetchMediaGroups({ ...baseFilters, year })
        .then((months) => {
          setMonthsByYear((prev) => new Map(prev).set(yearGroupKey, months));
        })
        .finally(() => {
          setMonthsLoading((prev) => {
            const next = new Set(prev);
            next.delete(yearGroupKey);
            return next;
          });
        });
    },
    [baseFilters]
  );

  const loadLeafPage = useCallback(
    (leafGroupKey: string, offset: number) => {
      const params: Parameters<typeof fetchMediaGroupItems>[0] = {
        ...baseFilters,
        sort: groupBy,
        offset,
        limit: PAGE_SIZE,
      };
      if (groupBy === "date") {
        if (leafGroupKey.startsWith("date:month:")) {
          const parsed = parseMonth(leafGroupKey);
          if (!parsed) return;
          params.year = parsed.year;
          params.month = parsed.month;
        } else if (isUnknownYear({ group_key: leafGroupKey } as MediaGroup)) {
          params.unknown = true;
        }
      } else {
        params.bucket = parseBucket(leafGroupKey);
      }

      setItemsByGroup((prev) => {
        const next = new Map(prev);
        const current = next.get(leafGroupKey) ?? { items: [], total: 0, hasMore: true, loading: false };
        if (current.loading) return prev;
        next.set(leafGroupKey, { ...current, loading: true });
        return next;
      });

      fetchMediaGroupItems(params)
        .then((page) => {
          setItemsByGroup((prev) => {
            const next = new Map(prev);
            const current = next.get(leafGroupKey) ?? { items: [], total: 0, hasMore: true, loading: false };
            const merged = offset === 0 ? page.items : [...current.items, ...page.items];
            next.set(leafGroupKey, {
              items: merged,
              total: page.total,
              hasMore: page.has_more,
              loading: false,
            });
            return next;
          });
          if (page.items.length > 0) {
            onItemsLoadedRef.current?.(page.items);
          }
        })
        .catch(() => {
          setItemsByGroup((prev) => {
            const next = new Map(prev);
            const current = next.get(leafGroupKey);
            if (current) next.set(leafGroupKey, { ...current, loading: false });
            return next;
          });
        });
    },
    [baseFilters, groupBy]
  );

  const toggleYear = (group: MediaGroup) => {
    const key = group.group_key;
    const isOpen = expanded.has(key);
    setExpanded((prev) => {
      const next = new Set(prev);
      if (isOpen) next.delete(key);
      else next.add(key);
      return next;
    });
    if (isOpen) return;
    // Unknown-date year is a leaf (no months); load items directly.
    if (isUnknownYear(group)) {
      if (!itemsByGroup.has(key)) loadLeafPage(key, 0);
      return;
    }
    if (!monthsByYear.has(key)) loadMonths(key);
  };

  const toggleLeaf = (leafGroupKey: string) => {
    const isOpen = expanded.has(leafGroupKey);
    setExpanded((prev) => {
      const next = new Set(prev);
      if (isOpen) next.delete(leafGroupKey);
      else next.add(leafGroupKey);
      return next;
    });
    if (!isOpen && !itemsByGroup.has(leafGroupKey)) {
      loadLeafPage(leafGroupKey, 0);
    }
  };

  const renderLeafBody = (leafGroupKey: string) => {
    const state = itemsByGroup.get(leafGroupKey);
    const items = state?.items ?? [];
    const loadedKeys = items.map(mediaItemKey);
    const selectedInGroup = selectionMode
      ? loadedKeys.filter((k) => selectedKeys.has(k)).length
      : 0;
    const groupChecked = selectedInGroup > 0 && selectedInGroup === loadedKeys.length;
    const groupIndeterminate = selectedInGroup > 0 && selectedInGroup < loadedKeys.length;

    return (
      <>
        {selectionMode && loadedKeys.length > 0 ? (
          <div className="grouped-media-select-row">
            <GroupCheckbox
              checked={groupChecked}
              indeterminate={groupIndeterminate}
              onChange={() => onToggleGroupItems(items)}
              label="Select all loaded items in this group"
            />
            <span className="video-group-select-count">
              {selectedInGroup} / {loadedKeys.length} selected
            </span>
          </div>
        ) : null}

        {items.length > 0 ? (
          <div className="video-grid video-grid-grouped">
            {items.map((item) => (
              <MediaCard
                key={mediaItemKey(item)}
                item={item}
                selectionMode={selectionMode}
                selected={selectedKeys.has(mediaItemKey(item))}
                onToggleSelect={onToggleItem}
              />
            ))}
          </div>
        ) : null}

        {state?.loading ? <div className="grouped-media-loading">Loading...</div> : null}

        {state && state.hasMore ? (
          <InfiniteScrollSentinel
            disabled={state.loading}
            onVisible={() => loadLeafPage(leafGroupKey, items.length)}
          />
        ) : null}
      </>
    );
  };

  if (topLoading) return <div className="status">Loading...</div>;
  if (topError) return <div className="error">{topError}</div>;
  if (topGroups.length === 0) return <div className="status">{emptyMessage}</div>;

  return (
    <div className="grouped-media-browser">
      {topGroups.map((group) => {
        const isYear = group.group_type === "year";
        const isOpen = expanded.has(group.group_key);

        if (isYear && !isUnknownYear(group)) {
          const months = monthsByYear.get(group.group_key) ?? [];
          const loadingMonths = monthsLoading.has(group.group_key);
          return (
            <section key={group.group_key} className="grouped-media-year">
              <button className="grouped-media-header grouped-media-year-header" onClick={() => toggleYear(group)}>
                <span className="grouped-media-caret">{isOpen ? "▼" : "▶"}</span>
                <span className="grouped-media-label">{group.label}</span>
                <span className="grouped-media-count">{group.count.toLocaleString()}</span>
              </button>
              {isOpen ? (
                <div className="grouped-media-children">
                  {loadingMonths ? <div className="grouped-media-loading">Loading...</div> : null}
                  {months.map((month) => {
                    const monthOpen = expanded.has(month.group_key);
                    return (
                      <section key={month.group_key} className="grouped-media-month">
                        <button
                          className="grouped-media-header grouped-media-month-header"
                          onClick={() => toggleLeaf(month.group_key)}
                        >
                          <span className="grouped-media-caret">{monthOpen ? "▼" : "▶"}</span>
                          <span className="grouped-media-label">{month.label}</span>
                          <span className="grouped-media-count">{month.count.toLocaleString()}</span>
                        </button>
                        {monthOpen ? (
                          <div className="grouped-media-items">{renderLeafBody(month.group_key)}</div>
                        ) : null}
                      </section>
                    );
                  })}
                </div>
              ) : null}
            </section>
          );
        }

        // Leaf-style group: bucket, or unknown-date year.
        return (
          <section key={group.group_key} className="grouped-media-month grouped-media-leaf">
            <button
              className="grouped-media-header grouped-media-month-header"
              onClick={() => (isYear ? toggleYear(group) : toggleLeaf(group.group_key))}
            >
              <span className="grouped-media-caret">{isOpen ? "▼" : "▶"}</span>
              <span className="grouped-media-label">{group.label}</span>
              <span className="grouped-media-count">{group.count.toLocaleString()}</span>
            </button>
            {isOpen ? <div className="grouped-media-items">{renderLeafBody(group.group_key)}</div> : null}
          </section>
        );
      })}
    </div>
  );
}
