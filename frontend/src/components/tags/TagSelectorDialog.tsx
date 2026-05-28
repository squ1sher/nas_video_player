import { useEffect, useMemo, useState } from "react";

import { createTag, getTagTree, getTags, patchTagTree } from "../../api/client";
import type { TagItem, TagTreeMove, TagTreeNode } from "../../types/video";
import { CreateTagDialog } from "./CreateTagDialog";
import { TagTree } from "./TagTree";

type PendingTreeChange = {
  new_parent_id?: number | null;
  new_name?: string;
};

type Props = {
  open: boolean;
  title: string;
  subtitle?: string;
  confirmLabel: string;
  disabledIds?: Set<number>;
  initialSelectedIds?: Set<number>;
  onClose: () => void;
  onApply: (tagIds: number[]) => Promise<void>;
  onTreeSaved?: () => Promise<void> | void;
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

function findPathToNode(nodes: TagTreeNode[], targetId: number): number[] {
  const walk = (current: TagTreeNode[], path: number[]): number[] | null => {
    for (const node of current) {
      const nextPath = [...path, node.id];
      if (node.id === targetId) return nextPath;
      const inChildren = walk(node.children, nextPath);
      if (inChildren) return inChildren;
    }
    return null;
  };
  return walk(nodes, []) ?? [];
}

function cloneTree(nodes: TagTreeNode[]): TagTreeNode[] {
  return nodes.map((node) => ({ ...node, children: cloneTree(node.children) }));
}

function collectParentMap(nodes: TagTreeNode[], parentId: number | null = null, map = new Map<number, number | null>()): Map<number, number | null> {
  for (const node of nodes) {
    map.set(node.id, parentId);
    collectParentMap(node.children, node.id, map);
  }
  return map;
}

function collectNodeMap(nodes: TagTreeNode[], map = new Map<number, TagTreeNode>()): Map<number, TagTreeNode> {
  for (const node of nodes) {
    map.set(node.id, node);
    collectNodeMap(node.children, map);
  }
  return map;
}

function removeNode(nodes: TagTreeNode[], targetId: number): { removed: TagTreeNode | null; nodes: TagTreeNode[] } {
  const next: TagTreeNode[] = [];
  let removed: TagTreeNode | null = null;

  for (const node of nodes) {
    if (node.id === targetId) {
      removed = node;
      continue;
    }
    const childResult = removeNode(node.children, targetId);
    if (childResult.removed) {
      removed = childResult.removed;
      next.push({ ...node, children: childResult.nodes });
    } else {
      next.push(node);
    }
  }

  return { removed, nodes: next };
}

function insertNode(nodes: TagTreeNode[], parentId: number | null, nodeToInsert: TagTreeNode): TagTreeNode[] {
  if (parentId === null) {
    return [...nodes, nodeToInsert];
  }

  let inserted = false;
  const next = nodes.map((node) => {
    if (node.id === parentId) {
      inserted = true;
      return { ...node, children: [...node.children, nodeToInsert] };
    }
    const updatedChildren = insertNode(node.children, parentId, nodeToInsert);
    if (updatedChildren !== node.children) {
      inserted = true;
      return { ...node, children: updatedChildren };
    }
    return node;
  });

  return inserted ? next : nodes;
}

function isDescendant(parentMap: Map<number, number | null>, ancestorId: number, possibleDescendantId: number): boolean {
  let current: number | null | undefined = possibleDescendantId;
  while (current !== null && current !== undefined) {
    if (current === ancestorId) return true;
    current = parentMap.get(current);
  }
  return false;
}

function normalizeDraftTree(nodes: TagTreeNode[], parentId: number | null = null, parentPath = "", depth = 0): TagTreeNode[] {
  return nodes.map((node) => {
    const path = parentPath ? `${parentPath}/${node.name}` : node.name;
    return {
      ...node,
      parent_id: parentId,
      path,
      depth,
      children: normalizeDraftTree(node.children, node.id, path, depth + 1),
    };
  });
}

function renameNode(nodes: TagTreeNode[], tagId: number, newName: string): TagTreeNode[] {
  return nodes.map((node) => {
    if (node.id === tagId) {
      return { ...node, name: newName };
    }
    if (node.children.length === 0) return node;
    return { ...node, children: renameNode(node.children, tagId, newName) };
  });
}

export function TagSelectorDialog({
  open,
  title,
  subtitle,
  confirmLabel,
  disabledIds,
  initialSelectedIds,
  onClose,
  onApply,
  onTreeSaved,
}: Props) {
  const [tree, setTree] = useState<TagTreeNode[]>([]);
  const [flatTags, setFlatTags] = useState<TagItem[]>([]);
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set());
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [selectedNodeId, setSelectedNodeId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [editMode, setEditMode] = useState(false);
  const [draftTree, setDraftTree] = useState<TagTreeNode[] | null>(null);
  const [originalTree, setOriginalTree] = useState<TagTreeNode[] | null>(null);
  const [pendingChanges, setPendingChanges] = useState<Map<number, PendingTreeChange>>(new Map());
  const [draggedTagId, setDraggedTagId] = useState<number | null>(null);
  const [editingTagId, setEditingTagId] = useState<number | null>(null);
  const [editingName, setEditingName] = useState("");

  const currentTree = editMode && draftTree ? draftTree : tree;
  const originalParentMap = useMemo(() => (originalTree ? collectParentMap(originalTree) : new Map<number, number | null>()), [originalTree]);
  const originalNodeMap = useMemo(() => (originalTree ? collectNodeMap(originalTree) : new Map<number, TagTreeNode>()), [originalTree]);
  const currentParentMap = useMemo(() => collectParentMap(currentTree), [currentTree]);

  const selectedTags = useMemo(() => {
    if (selectedIds.size === 0) return [];
    const selected = new Set(selectedIds);
    return flatTags.filter((tag) => selected.has(tag.id));
  }, [flatTags, selectedIds]);

  const loadTree = async (createdTagId?: number) => {
    const prevExpanded = expandedIds;
    const [tagTree, tagsFlat] = await Promise.all([getTagTree(), getTags()]);
    setTree(tagTree);
    setFlatTags(tagsFlat);

    const allIds = collectIds(tagTree);
    if (prevExpanded.size === 0) {
      setExpandedIds(allIds);
      return;
    }

    const nextExpanded = new Set<number>();
    prevExpanded.forEach((id) => {
      if (allIds.has(id)) nextExpanded.add(id);
    });

    if (createdTagId) {
      findPathToNode(tagTree, createdTagId).forEach((id) => nextExpanded.add(id));
    }

    setExpandedIds(nextExpanded);
  };

  const closeDialog = () => {
    setEditMode(false);
    setDraftTree(null);
    setOriginalTree(null);
    setPendingChanges(new Map());
    setDraggedTagId(null);
    setEditingTagId(null);
    setEditingName("");
    onClose();
  };

  useEffect(() => {
    if (!open) return;
    setError(null);
    setSelectedNodeId(null);
    setSelectedIds(initialSelectedIds ? new Set(initialSelectedIds) : new Set());
    setEditMode(false);
    setDraftTree(null);
    setOriginalTree(null);
    setPendingChanges(new Map());
    setDraggedTagId(null);
    setEditingTagId(null);
    setEditingName("");

    setLoading(true);
    void loadTree()
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load tags."))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  if (!open) return null;

  const toggleExpand = (tagId: number) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(tagId)) next.delete(tagId);
      else next.add(tagId);
      return next;
    });
  };

  const toggleSelected = (tagId: number, checked: boolean) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (checked) next.add(tagId);
      else next.delete(tagId);
      return next;
    });
  };

  const enterEditMode = () => {
    setError(null);
    setEditMode(true);
    setOriginalTree(cloneTree(tree));
    setDraftTree(normalizeDraftTree(cloneTree(tree)));
    setPendingChanges(new Map());
    setEditingTagId(null);
    setEditingName("");
  };

  const cancelEditMode = () => {
    setError(null);
    setEditMode(false);
    setDraftTree(null);
    setOriginalTree(null);
    setPendingChanges(new Map());
    setDraggedTagId(null);
    setEditingTagId(null);
    setEditingName("");
  };

  const registerChange = (tagId: number, nextChange: PendingTreeChange) => {
    setPendingChanges((prev) => {
      const next = new Map(prev);
      const originalParentId = originalParentMap.get(tagId) ?? null;
      const originalName = originalNodeMap.get(tagId)?.name ?? "";
      const current = next.get(tagId) ?? {};
      const merged: PendingTreeChange = { ...current, ...nextChange };

      if ((merged.new_parent_id ?? originalParentId) === originalParentId) {
        delete merged.new_parent_id;
      }
      if (merged.new_name !== undefined && merged.new_name === originalName) {
        delete merged.new_name;
      }

      if (merged.new_parent_id === undefined && merged.new_name === undefined) next.delete(tagId);
      else next.set(tagId, merged);
      return next;
    });
  };

  const moveTag = (targetParentId: number | null) => {
    if (!editMode || draggedTagId === null || !draftTree) return;
    const currentParentId = currentParentMap.get(draggedTagId) ?? null;
    if (currentParentId === targetParentId) {
      setDraggedTagId(null);
      return;
    }
    if (targetParentId === draggedTagId) {
      setError("Cannot move a tag under itself.");
      setDraggedTagId(null);
      return;
    }
    if (targetParentId !== null && isDescendant(currentParentMap, draggedTagId, targetParentId)) {
      setError("Cannot move a tag under its descendant.");
      setDraggedTagId(null);
      return;
    }

    const treeClone = cloneTree(draftTree);
    const removed = removeNode(treeClone, draggedTagId);
    if (!removed.removed) {
      setError("Failed to move tag in draft tree.");
      setDraggedTagId(null);
      return;
    }

    const inserted = normalizeDraftTree(insertNode(removed.nodes, targetParentId, removed.removed));
    if (targetParentId !== null && inserted === removed.nodes) {
      setError("Invalid drop target.");
      setDraggedTagId(null);
      return;
    }

    setDraftTree(inserted);
    registerChange(draggedTagId, { new_parent_id: targetParentId });
    setError(null);
    setDraggedTagId(null);
  };

  const beginRename = (tagId: number) => {
    const node = collectNodeMap(currentTree).get(tagId);
    if (!node) return;
    setSelectedNodeId(tagId);
    setEditingTagId(tagId);
    setEditingName(node.name);
    setError(null);
  };

  const cancelRename = () => {
    setEditingTagId(null);
    setEditingName("");
  };

  const commitRename = () => {
    if (!editMode || editingTagId === null || !draftTree) return;
    const trimmed = editingName.trim();
    if (!trimmed) {
      setError("Tag name cannot be empty.");
      return;
    }

    const renamed = normalizeDraftTree(renameNode(cloneTree(draftTree), editingTagId, trimmed));
    setDraftTree(renamed);
    registerChange(editingTagId, { new_name: trimmed });
    setEditingTagId(null);
    setEditingName("");
    setError(null);
  };

  const handleApply = async () => {
    setBusy(true);
    setError(null);
    try {
      await onApply([...selectedIds]);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to apply tags.");
    } finally {
      setBusy(false);
    }
  };

  const handleSaveTree = async () => {
    if (!editMode) return;
    if (pendingChanges.size === 0) {
      cancelEditMode();
      return;
    }

    setBusy(true);
    setError(null);
    try {
      const moves: TagTreeMove[] = [...pendingChanges.entries()].map(([tag_id, change]) => ({
        tag_id,
        new_parent_id: change.new_parent_id ?? (originalParentMap.get(tag_id) ?? null),
        ...(change.new_name !== undefined ? { new_name: change.new_name } : {}),
      }));
      const response = await patchTagTree(moves);
      setTree(response.tree);
      setExpandedIds(collectIds(response.tree));
      await loadTree();
      await onTreeSaved?.();
      cancelEditMode();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save tag tree changes.");
    } finally {
      setBusy(false);
    }
  };

  const handleCreateTag = async (payload: { name: string; parent_id: number | null; assignToVideo: boolean }) => {
    void payload.assignToVideo;
    const created = await createTag({ name: payload.name, parent_id: payload.parent_id });
    await loadTree(created.id);
    setSelectedIds((prev) => new Set([...prev, created.id]));
    setSelectedNodeId(created.id);
  };

  return (
    <div className="modal-overlay" onClick={closeDialog}>
      <div className="modal-box" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <h3>{editMode ? "Edit tag tree" : title}</h3>
          <button className="modal-close" onClick={closeDialog}>x</button>
        </div>
        <div className="modal-body">
          {subtitle ? <p className="form-hint">{subtitle}</p> : null}
          {error ? <div className="settings-error">{error}</div> : null}

          <div className="settings-inline-actions" style={{ marginBottom: 10 }}>
            {!editMode ? (
              <>
                <button className="btn-secondary" onClick={() => setCreateOpen(true)} disabled={busy || loading}>
                  Create new tag
                </button>
                <button className="btn-secondary" onClick={enterEditMode} disabled={busy || loading || tree.length === 0}>
                  Edit
                </button>
              </>
            ) : null}
          </div>

          {editMode ? (
            <p className="form-hint">
              Drag tags to reorganize the tree or double-click a tag name to rename it. Changes are applied to all videos using these tags after saving.
            </p>
          ) : null}

          {editMode ? (
            <div
              className="tag-root-dropzone"
              onDragOver={(event) => {
                if (!editMode) return;
                event.preventDefault();
              }}
              onDrop={(event) => {
                event.preventDefault();
                moveTag(null);
              }}
            >
              Root level (drop here)
            </div>
          ) : null}

          {loading ? (
            <div className="settings-loading">Loading tags...</div>
          ) : currentTree.length === 0 ? (
            <div className="settings-empty">No tags created yet.</div>
          ) : (
            <TagTree
              nodes={currentTree}
              expandedIds={expandedIds}
              selectedIds={editMode ? undefined : selectedIds}
              disabledIds={disabledIds}
              onToggleExpand={toggleExpand}
              onToggleSelect={editMode ? undefined : toggleSelected}
              onSelectNode={setSelectedNodeId}
              selectedNodeId={selectedNodeId}
              showVideoCount
              draggableMode={editMode}
              onDragStartTag={setDraggedTagId}
              onDropOnTag={moveTag}
              canDropOnTag={(targetTagId) => {
                if (draggedTagId === null) return false;
                if (targetTagId === draggedTagId) return false;
                return !isDescendant(currentParentMap, draggedTagId, targetTagId);
              }}
              editingTagId={editingTagId}
              editingName={editingName}
              onBeginRename={beginRename}
              onEditingNameChange={setEditingName}
              onCommitRename={commitRename}
              onCancelRename={cancelRename}
            />
          )}

          {!editMode ? (
            <div className="watch-tag-chip-list" style={{ marginTop: 12 }}>
              {selectedTags.length === 0 ? (
                <span className="watch-tag-empty">No tags selected.</span>
              ) : (
                selectedTags.map((tag) => (
                  <span key={tag.id} className="thumb-tag-chip" title={tag.path}>{tag.path}</span>
                ))
              )}
            </div>
          ) : null}
        </div>
        <div className="modal-footer">
          {editMode ? (
            <>
              <button className="btn-secondary" onClick={cancelEditMode} disabled={busy}>Cancel</button>
              <button className="btn-primary" onClick={() => void handleSaveTree()} disabled={busy || loading}>
                {busy ? "Saving..." : "Save"}
              </button>
            </>
          ) : (
            <>
              <button className="btn-secondary" onClick={closeDialog} disabled={busy}>Cancel</button>
              <button className="btn-primary" onClick={() => void handleApply()} disabled={busy || loading}>
                {busy ? "Saving..." : confirmLabel}
              </button>
            </>
          )}
        </div>
      </div>

      <CreateTagDialog
        open={createOpen}
        title="Create new tag"
        tagsFlat={flatTags}
        defaultParentId={selectedNodeId}
        onClose={() => setCreateOpen(false)}
        onConfirm={handleCreateTag}
      />
    </div>
  );
}

