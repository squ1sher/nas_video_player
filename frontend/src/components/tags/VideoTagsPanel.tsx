import { useEffect, useMemo, useState } from "react";

import { addVideoTags, createTag, getTagTree, getTags, getVideoTags, removeVideoTag } from "../../api/client";
import type { TagItem, TagTreeNode, VideoTag } from "../../types/video";
import { CreateTagDialog } from "./CreateTagDialog";
import { TagChip } from "./TagChip";
import { TagTree } from "./TagTree";

type Props = {
  videoId: number;
  onTagsChanged?: (tags: VideoTag[]) => void;
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

function allTagIdsFromTree(nodes: TagTreeNode[]): Set<number> {
  return collectIds(nodes);
}

export function VideoTagsPanel({ videoId, onTagsChanged }: Props) {
  const [assignedTags, setAssignedTags] = useState<VideoTag[]>([]);
  const [tree, setTree] = useState<TagTreeNode[]>([]);
  const [flatTags, setFlatTags] = useState<TagItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [selectorOpen, setSelectorOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set());
  const [selectedToAdd, setSelectedToAdd] = useState<Set<number>>(new Set());

  const assignedIds = useMemo(() => new Set(assignedTags.map((tag) => tag.id)), [assignedTags]);

  const loadAll = async () => {
    setLoading(true);
    try {
      const [videoTags, tagTree, tagsFlat] = await Promise.all([
        getVideoTags(videoId),
        getTagTree(),
        getTags(),
      ]);
      setAssignedTags(videoTags);
      setTree(tagTree);
      setFlatTags(tagsFlat);
      onTagsChanged?.(videoTags);
      setError(null);
      if (expandedIds.size === 0) {
        setExpandedIds(allTagIdsFromTree(tagTree));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load tags.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [videoId]);

  const toggleExpand = (tagId: number) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(tagId)) next.delete(tagId);
      else next.add(tagId);
      return next;
    });
  };

  const toggleSelected = (tagId: number, checked: boolean) => {
    setSelectedToAdd((prev) => {
      const next = new Set(prev);
      if (checked) next.add(tagId);
      else next.delete(tagId);
      return next;
    });
  };

  const handleAssignSelected = async () => {
    const newTagIds = [...selectedToAdd].filter((id) => !assignedIds.has(id));
    if (newTagIds.length === 0) {
      setSelectorOpen(false);
      setSelectedToAdd(new Set());
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const updated = await addVideoTags(videoId, newTagIds);
      setAssignedTags(updated);
      onTagsChanged?.(updated);
      setSelectedToAdd(new Set());
      setSelectorOpen(false);
      setMessage(`Added ${newTagIds.length} tag(s).`);
      const [tagTree, tagsFlat] = await Promise.all([getTagTree(), getTags()]);
      setTree(tagTree);
      setFlatTags(tagsFlat);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to assign tags.");
    } finally {
      setBusy(false);
    }
  };

  const handleRemove = async (tagId: number) => {
    setBusy(true);
    setError(null);
    try {
      await removeVideoTag(videoId, tagId);
      const updated = await getVideoTags(videoId);
      setAssignedTags(updated);
      onTagsChanged?.(updated);
      setMessage("Tag removed.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to remove tag.");
    } finally {
      setBusy(false);
    }
  };

  const handleCreateTag = async (payload: { name: string; parent_id: number | null; assignToVideo: boolean }) => {
    const created = await createTag({ name: payload.name, parent_id: payload.parent_id });
    if (payload.assignToVideo) {
      const updated = await addVideoTags(videoId, [created.id]);
      setAssignedTags(updated);
      onTagsChanged?.(updated);
    }
    const [tagTree, tagsFlat] = await Promise.all([getTagTree(), getTags()]);
    setTree(tagTree);
    setFlatTags(tagsFlat);
    setMessage(`Tag \"${created.path}\" created.`);
  };

  return (
    <section className="watch-tags-panel">
      <div className="watch-tags-header">
        <h2>Tags</h2>
        <div className="watch-tags-actions">
          <button className="btn-secondary" onClick={() => setSelectorOpen(true)} disabled={loading || busy}>Add tags</button>
          <button className="btn-secondary" onClick={() => setCreateOpen(true)} disabled={loading || busy}>Create tag</button>
        </div>
      </div>

      {loading ? <div className="settings-loading">Loading tags...</div> : null}
      {error ? <div className="settings-error">{error}</div> : null}
      {message ? <div className="settings-notice">{message}</div> : null}

      <div className="watch-tag-chip-list">
        {assignedTags.length === 0 ? (
          <span className="watch-tag-empty">No tags assigned.</span>
        ) : (
          assignedTags.map((tag) => (
            <TagChip key={tag.id} tag={tag} removable onRemove={(tagId) => void handleRemove(tagId)} />
          ))
        )}
      </div>

      {selectorOpen ? (
        <div className="modal-overlay" onClick={() => setSelectorOpen(false)}>
          <div className="modal-box" onClick={(event) => event.stopPropagation()}>
            <div className="modal-header">
              <h3>Select tags</h3>
              <button className="modal-close" onClick={() => setSelectorOpen(false)}>x</button>
            </div>
            <div className="modal-body">
              {tree.length === 0 ? (
                <div className="settings-empty">No tags created yet.</div>
              ) : (
                <TagTree
                  nodes={tree}
                  expandedIds={expandedIds}
                  selectedIds={selectedToAdd}
                  disabledIds={assignedIds}
                  onToggleExpand={toggleExpand}
                  onToggleSelect={toggleSelected}
                  showVideoCount
                />
              )}
            </div>
            <div className="modal-footer">
              <button className="btn-secondary" onClick={() => setSelectorOpen(false)} disabled={busy}>Cancel</button>
              <button className="btn-primary" onClick={() => void handleAssignSelected()} disabled={busy}>
                {busy ? "Saving..." : "Add selected"}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      <CreateTagDialog
        open={createOpen}
        title="Create tag"
        tagsFlat={flatTags}
        onClose={() => setCreateOpen(false)}
        onConfirm={handleCreateTag}
        allowAssignToVideo
      />
    </section>
  );
}

