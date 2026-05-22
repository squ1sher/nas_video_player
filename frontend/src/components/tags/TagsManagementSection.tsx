import { useEffect, useMemo, useState } from "react";

import { createTag, deleteTag, getTagTree, getTags, updateTag } from "../../api/client";
import type { TagItem, TagTreeNode } from "../../types/video";
import { CreateTagDialog } from "./CreateTagDialog";
import { TagTree } from "./TagTree";

type Props = {
  onChanged?: () => void;
};

function flattenTree(nodes: TagTreeNode[]): TagTreeNode[] {
  const result: TagTreeNode[] = [];
  const stack = [...nodes].reverse();
  while (stack.length > 0) {
    const node = stack.pop();
    if (!node) continue;
    result.push(node);
    for (const child of [...node.children].reverse()) {
      stack.push(child);
    }
  }
  return result;
}

export function TagsManagementSection({ onChanged }: Props) {
  const [tree, setTree] = useState<TagTreeNode[]>([]);
  const [flatTags, setFlatTags] = useState<TagItem[]>([]);
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set());
  const [selectedTagId, setSelectedTagId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [createChildOpen, setCreateChildOpen] = useState(false);
  const [editName, setEditName] = useState("");
  const [editParentId, setEditParentId] = useState<number | null>(null);

  const selectedTag = useMemo(
    () => flatTags.find((tag) => tag.id === selectedTagId) ?? null,
    [flatTags, selectedTagId]
  );

  const load = async () => {
    setLoading(true);
    try {
      const [nextTree, nextFlat] = await Promise.all([getTagTree(), getTags()]);
      setTree(nextTree);
      setFlatTags(nextFlat);
      setError(null);
      setExpandedIds(new Set(flattenTree(nextTree).map((node) => node.id)));
      if (selectedTagId && !nextFlat.some((tag) => tag.id === selectedTagId)) {
        setSelectedTagId(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load tags.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!selectedTag) {
      setEditName("");
      setEditParentId(null);
      return;
    }
    setEditName(selectedTag.name);
    setEditParentId(selectedTag.parent_id);
  }, [selectedTag]);

  const handleCreate = async (payload: { name: string; parent_id: number | null; assignToVideo: boolean }) => {
    void payload.assignToVideo;
    await createTag({ name: payload.name, parent_id: payload.parent_id });
    await load();
    onChanged?.();
    setMessage("Tag created.");
  };

  const handleSaveEdit = async () => {
    if (!selectedTag) return;
    setBusy(true);
    setError(null);
    try {
      await updateTag(selectedTag.id, { name: editName.trim(), parent_id: editParentId });
      await load();
      onChanged?.();
      setMessage("Tag updated.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update tag.");
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async () => {
    if (!selectedTag) return;
    const confirmed = window.confirm(
      "Delete selected tag?\n\nVideos will not be deleted. This tag will be removed from all videos."
    );
    if (!confirmed) return;

    setBusy(true);
    setError(null);
    try {
      await deleteTag(selectedTag.id);
      await load();
      onChanged?.();
      setSelectedTagId(null);
      setMessage("Tag deleted.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete tag.");
    } finally {
      setBusy(false);
    }
  };

  const toggleExpand = (tagId: number) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(tagId)) next.delete(tagId);
      else next.add(tagId);
      return next;
    });
  };

  return (
    <section className="settings-section" id="tags">
      <div className="settings-section-header">
        <div>
          <h2>Tags</h2>
          <p className="settings-section-desc">Manage hierarchical tags used on the Watch page and Library hover overlay.</p>
        </div>
        <div className="settings-inline-actions">
          <button className="btn-secondary" onClick={() => void load()} disabled={loading || busy}>Refresh</button>
          <button className="btn-primary" onClick={() => setCreateOpen(true)} disabled={loading || busy}>+ Create top-level tag</button>
        </div>
      </div>

      {message ? <div className="settings-notice">{message}</div> : null}
      {error ? <div className="settings-error">{error}</div> : null}

      {loading ? (
        <div className="settings-loading">Loading tags...</div>
      ) : tree.length === 0 ? (
        <div className="settings-empty">No tags created yet.</div>
      ) : (
        <div className="tags-settings-grid">
          <div className="tags-tree-panel">
            <TagTree
              nodes={tree}
              expandedIds={expandedIds}
              onToggleExpand={toggleExpand}
              onSelectNode={(tagId) => setSelectedTagId(tagId)}
              selectedNodeId={selectedTagId}
              showVideoCount
            />
          </div>
          <div className="tags-editor-panel">
            {selectedTag ? (
              <>
                <h3>{selectedTag.path}</h3>
                <label className="form-label">
                  Name
                  <input
                    className="form-input"
                    value={editName}
                    onChange={(event) => setEditName(event.target.value)}
                  />
                </label>
                <label className="form-label">
                  Parent
                  <select
                    className="form-input"
                    value={editParentId === null ? "" : String(editParentId)}
                    onChange={(event) => {
                      const value = event.target.value;
                      setEditParentId(value ? Number(value) : null);
                    }}
                  >
                    <option value="">Top level</option>
                    {flatTags
                      .filter((tag) => tag.id !== selectedTag.id)
                      .map((tag) => (
                        <option key={tag.id} value={tag.id}>{`${"  ".repeat(tag.depth)}${tag.path}`}</option>
                      ))}
                  </select>
                </label>

                <div className="settings-inline-actions">
                  <button className="btn-secondary" onClick={() => setCreateChildOpen(true)} disabled={busy}>Create child</button>
                  <button className="btn-secondary" onClick={() => void handleSaveEdit()} disabled={busy}>Save</button>
                  <button className="btn-danger" onClick={() => void handleDelete()} disabled={busy}>Delete</button>
                </div>
              </>
            ) : (
              <div className="settings-empty">Select a tag in the tree to rename, move, or delete.</div>
            )}
          </div>
        </div>
      )}

      <CreateTagDialog
        open={createOpen}
        title="Create top-level tag"
        tagsFlat={flatTags}
        defaultParentId={null}
        onClose={() => setCreateOpen(false)}
        onConfirm={handleCreate}
      />

      <CreateTagDialog
        open={createChildOpen}
        title="Create child tag"
        tagsFlat={flatTags}
        defaultParentId={selectedTagId}
        onClose={() => setCreateChildOpen(false)}
        onConfirm={handleCreate}
      />
    </section>
  );
}

