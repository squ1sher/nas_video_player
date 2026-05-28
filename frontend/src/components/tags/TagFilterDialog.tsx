import { useEffect, useMemo, useState } from "react";

import { getTagTree, getTags } from "../../api/client";
import type { TagTreeNode } from "../../types/video";
import { TagTree } from "./TagTree";

export type TagFilterMode = "any" | "all";

export type TagFilterState = {
  selectedTagIds: number[];
  mode: TagFilterMode;
  withoutTags: boolean;
};

type SelectedTag = {
  id: number;
  path: string;
};

type Props = {
  open: boolean;
  initialState: TagFilterState;
  onClose: () => void;
  onApply: (nextState: TagFilterState, selectedTags: SelectedTag[]) => void;
};

function collectIds(nodes: TagTreeNode[]): Set<number> {
  const ids = new Set<number>();
  const stack = [...nodes];
  while (stack.length > 0) {
    const node = stack.pop();
    if (!node) continue;
    ids.add(node.id);
    for (const child of node.children) stack.push(child);
  }
  return ids;
}

export function TagFilterDialog({ open, initialState, onClose, onApply }: Props) {
  const [tree, setTree] = useState<TagTreeNode[]>([]);
  const [flatTags, setFlatTags] = useState<Array<{ id: number; path: string }>>([]);
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set());
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [mode, setMode] = useState<TagFilterMode>("any");
  const [withoutTags, setWithoutTags] = useState(false);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedTags = useMemo(() => {
    if (selectedIds.size === 0) return [];
    return flatTags.filter((tag) => selectedIds.has(tag.id));
  }, [flatTags, selectedIds]);

  useEffect(() => {
    if (!open) return;

    setSelectedIds(new Set(initialState.selectedTagIds));
    setMode(initialState.mode);
    setWithoutTags(initialState.withoutTags);
    setError(null);

    setLoading(true);
    void Promise.all([getTagTree(), getTags()])
      .then(([tagTree, tagsFlat]) => {
        setTree(tagTree);
        setFlatTags(tagsFlat.map((tag) => ({ id: tag.id, path: tag.path })));
        setExpandedIds(collectIds(tagTree));
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load tags."))
      .finally(() => setLoading(false));
  }, [initialState.mode, initialState.selectedTagIds, initialState.withoutTags, open]);

  if (!open) return null;

  const handleToggleExpand = (tagId: number) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(tagId)) next.delete(tagId);
      else next.add(tagId);
      return next;
    });
  };

  const handleToggleSelect = (tagId: number, checked: boolean) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (checked) next.add(tagId);
      else next.delete(tagId);
      return next;
    });
    if (checked) setWithoutTags(false);
  };

  const handleToggleWithoutTags = (checked: boolean) => {
    setWithoutTags(checked);
    if (checked) {
      setSelectedIds(new Set());
    }
  };

  const handleClear = () => {
    setSelectedIds(new Set());
    setMode("any");
    setWithoutTags(false);
    setError(null);
    onApply({ selectedTagIds: [], mode: "any", withoutTags: false }, []);
    onClose();
  };

  const handleApply = () => {
    setBusy(true);
    setError(null);
    try {
      const nextState: TagFilterState = {
        selectedTagIds: withoutTags ? [] : [...selectedIds],
        mode,
        withoutTags,
      };
      onApply(nextState, withoutTags ? [] : selectedTags);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to apply tag filters.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <h3>Filter by tags</h3>
          <button className="modal-close" onClick={onClose}>x</button>
        </div>

        <div className="modal-body">
          {error ? <div className="settings-error">{error}</div> : null}

          <label className="checkbox-inline tag-filter-without-checkbox" style={{ marginBottom: 10 }}>
            <input
              type="checkbox"
              checked={withoutTags}
              onChange={(event) => handleToggleWithoutTags(event.target.checked)}
              disabled={busy || loading}
            />
            Without tags
          </label>

          <div className="tag-filter-mode-row">
            <span className="tag-filter-mode-label">Match mode:</span>
            <label>
              <input
                type="radio"
                name="tagFilterMode"
                value="any"
                checked={mode === "any"}
                onChange={() => setMode("any")}
                disabled={busy || loading || withoutTags}
              />
              Any selected tag
            </label>
            <label>
              <input
                type="radio"
                name="tagFilterMode"
                value="all"
                checked={mode === "all"}
                onChange={() => setMode("all")}
                disabled={busy || loading || withoutTags}
              />
              All selected tags
            </label>
          </div>

          {loading ? (
            <div className="settings-loading">Loading tags...</div>
          ) : tree.length === 0 ? (
            <div className="settings-empty">No tags created yet.</div>
          ) : (
            <div className={withoutTags ? "tag-filter-tree-disabled" : ""}>
              <TagTree
                nodes={tree}
                expandedIds={expandedIds}
                selectedIds={selectedIds}
                onToggleExpand={handleToggleExpand}
                onToggleSelect={handleToggleSelect}
              />
            </div>
          )}

          <div className="watch-tag-chip-list" style={{ marginTop: 12 }}>
            {withoutTags ? (
              <span className="thumb-tag-chip">Without tags</span>
            ) : selectedTags.length === 0 ? (
              <span className="watch-tag-empty">No tags selected.</span>
            ) : (
              selectedTags.map((tag) => (
                <span key={tag.id} className="thumb-tag-chip" title={tag.path}>{tag.path}</span>
              ))
            )}
          </div>
        </div>

        <div className="modal-footer">
          <button className="btn-secondary" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="btn-secondary" onClick={handleClear} disabled={busy || loading}>Clear</button>
          <button className="btn-primary" onClick={handleApply} disabled={busy || loading}>
            {busy ? "Applying..." : "Apply"}
          </button>
        </div>
      </div>
    </div>
  );
}

