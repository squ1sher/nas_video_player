import type { TagTreeNode } from "../../types/video";

type Props = {
  nodes: TagTreeNode[];
  expandedIds: Set<number>;
  selectedIds?: Set<number>;
  disabledIds?: Set<number>;
  onToggleExpand: (tagId: number) => void;
  onToggleSelect?: (tagId: number, checked: boolean) => void;
  onSelectNode?: (tagId: number) => void;
  selectedNodeId?: number | null;
  showVideoCount?: boolean;
};

export function TagTree({
  nodes,
  expandedIds,
  selectedIds,
  disabledIds,
  onToggleExpand,
  onToggleSelect,
  onSelectNode,
  selectedNodeId,
  showVideoCount = false,
}: Props) {
  return (
    <ul className="tag-tree-list">
      {nodes.map((node) => {
        const hasChildren = node.children.length > 0;
        const expanded = expandedIds.has(node.id);
        const selected = selectedIds?.has(node.id) ?? false;
        const disabled = disabledIds?.has(node.id) ?? false;
        const selectedNode = selectedNodeId === node.id;

        return (
          <li key={node.id} className="tag-tree-node">
            <div className={`tag-tree-row${selectedNode ? " tag-tree-row-selected" : ""}`}>
              <button
                type="button"
                className="tag-tree-toggle"
                onClick={() => hasChildren && onToggleExpand(node.id)}
                disabled={!hasChildren}
                aria-label={hasChildren ? (expanded ? "Collapse" : "Expand") : "No children"}
              >
                {hasChildren ? (expanded ? "v" : ">") : "-"}
              </button>

              {onToggleSelect && (
                <input
                  type="checkbox"
                  checked={selected}
                  disabled={disabled}
                  onChange={(event) => onToggleSelect(node.id, event.target.checked)}
                />
              )}

              <button
                type="button"
                className="tag-tree-name"
                onClick={() => onSelectNode?.(node.id)}
                title={node.path}
              >
                {node.name}
                {showVideoCount ? <span className="tag-tree-count">({node.video_count})</span> : null}
              </button>
            </div>

            {hasChildren && expanded && (
              <TagTree
                nodes={node.children}
                expandedIds={expandedIds}
                selectedIds={selectedIds}
                disabledIds={disabledIds}
                onToggleExpand={onToggleExpand}
                onToggleSelect={onToggleSelect}
                onSelectNode={onSelectNode}
                selectedNodeId={selectedNodeId}
                showVideoCount={showVideoCount}
              />
            )}
          </li>
        );
      })}
    </ul>
  );
}

