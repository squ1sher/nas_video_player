import { useMemo, useState } from "react";

import type { SortField, SortOrder } from "../../api/client";
import type { UnifiedMediaItem } from "../../types/video";
import type { MediaFolderTreeNode } from "../../utils/buildMediaFolderTree";
import { groupMediaItems } from "../../utils/groupMediaItems";
import { GroupToggleHeader } from "../GroupToggleHeader";

type Props = {
  root: MediaFolderTreeNode;
  expandedPaths: Set<string>;
  onToggle: (path: string) => void;
  sort: SortField;
  order: SortOrder;
  selectionMode?: boolean;
  selectedMediaKeys?: Set<string>;
  onToggleMediaSelect?: (item: UnifiedMediaItem) => void;
};

type NodeProps = {
  node: MediaFolderTreeNode;
  expandedPaths: Set<string>;
  onToggle: (path: string) => void;
  sort: SortField;
  order: SortOrder;
  selectionMode?: boolean;
  selectedMediaKeys?: Set<string>;
  onToggleMediaSelect?: (item: UnifiedMediaItem) => void;
};

function getMediaItemKey(item: UnifiedMediaItem): string {
  return `${item.type}:${item.id}`;
}

function folderMeta(node: MediaFolderTreeNode): string {
  const parts: string[] = [];
  if (node.children.length > 0) {
    parts.push(`${node.children.length} folder${node.children.length === 1 ? "" : "s"}`);
  }
  parts.push(`${node.totalItemCount} photo${node.totalItemCount === 1 ? "" : "s"}`);
  return parts.join(" - ");
}

function PhotoCard({
  item,
  selectionMode = false,
  selected = false,
  onToggleSelect,
}: {
  item: UnifiedMediaItem;
  selectionMode?: boolean;
  selected?: boolean;
  onToggleSelect?: (item: UnifiedMediaItem) => void;
}) {
  const itemContent = (
    <>
      <div className="thumb-wrap thumb-wrap-square">
        {item.thumbnail_url ? (
          <img
            src={item.thumbnail_url}
            alt={item.display_title}
            className="thumb"
            loading="lazy"
            onError={(e) => {
              e.currentTarget.style.visibility = "hidden";
            }}
          />
        ) : (
          <div className="thumb-fallback">No thumbnail</div>
        )}
        {item.raw_format ? (
          <span
            style={{
              position: "absolute",
              top: 6,
              left: 6,
              background: "rgba(0,0,0,0.7)",
              color: "#fff",
              fontSize: 10,
              fontWeight: 700,
              padding: "2px 6px",
              borderRadius: 4,
              letterSpacing: 0.5,
            }}
          >
            RAW
          </span>
        ) : null}
        {selectionMode ? (
          <label
            className="video-select-checkbox"
            onClick={(e) => e.stopPropagation()}
            title={selected ? "Deselect" : "Select"}
          >
            <input
              type="checkbox"
              checked={selected}
              onChange={() => onToggleSelect?.(item)}
            />
          </label>
        ) : null}
      </div>
    </>
  );

  if (selectionMode) {
    return (
      <button
        type="button"
        className={`video-card compact video-card-selection-mode${selected ? " video-card-selected" : ""}`}
        onClick={() => onToggleSelect?.(item)}
        title={item.display_title}
      >
        {itemContent}
      </button>
    );
  }

  return (
    <a
      className="video-card compact"
      href={`/photo/${item.id}`}
      target="_blank"
      rel="noopener noreferrer"
      title={item.display_title}
    >
      {itemContent}
    </a>
  );
}

function PhotoFolderNode({
  node,
  expandedPaths,
  onToggle,
  sort,
  order,
  selectionMode = false,
  selectedMediaKeys,
  onToggleMediaSelect,
}: NodeProps) {
  const isExpanded = expandedPaths.has(node.path);
  const canExpand = node.children.length > 0 || node.items.length > 0;
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
  const groups = useMemo(() => groupMediaItems(node.items, { sort, order }), [node.items, sort, order]);

  const toggleGroup = (groupKey: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(groupKey)) next.delete(groupKey);
      else next.add(groupKey);
      return next;
    });
  };

  return (
    <li className="folder-node" key={node.path}>
      <GroupToggleHeader
        expanded={isExpanded}
        onToggle={() => onToggle(node.path)}
        label={
          <>
            <span className="folder-node-icon">DIR</span>
            <span className="folder-name">{node.name}</span>
          </>
        }
        count={canExpand ? folderMeta(node) : undefined}
        size="md"
      />

      {isExpanded && (
        <div className="folder-children-wrap">
          {node.children.length > 0 && (
            <ul className="folder-node-list">
              {node.children.map((child) => (
                <PhotoFolderNode
                  key={child.path}
                  node={child}
                  expandedPaths={expandedPaths}
                  onToggle={onToggle}
                  sort={sort}
                  order={order}
                  selectionMode={selectionMode}
                  selectedMediaKeys={selectedMediaKeys}
                  onToggleMediaSelect={onToggleMediaSelect}
                />
              ))}
            </ul>
          )}

          {groups.length > 0 && (
            <div className="video-group-list folder-video-group-list">
              {groups.map((group) => {
                const groupRef = `${node.path}::${group.key}`;
                const isGroupCollapsed = collapsedGroups.has(groupRef);
                return (
                  <section key={groupRef} className="video-group-section">
                    <GroupToggleHeader
                      expanded={!isGroupCollapsed}
                      onToggle={() => toggleGroup(groupRef)}
                      label={group.title}
                      count={`${group.items.length} photos`}
                      size="md"
                    />
                    {!isGroupCollapsed && (
                      <div className="video-grid video-grid-grouped">
                        {group.items.map((item) => (
                          <PhotoCard
                            key={item.id}
                            item={item}
                            selectionMode={selectionMode}
                            selected={selectedMediaKeys?.has(getMediaItemKey(item)) ?? false}
                            onToggleSelect={onToggleMediaSelect}
                          />
                        ))}
                      </div>
                    )}
                  </section>
                );
              })}
            </div>
          )}
        </div>
      )}
    </li>
  );
}

export function PhotoFolderTree({
  root,
  expandedPaths,
  onToggle,
  sort,
  order,
  selectionMode = false,
  selectedMediaKeys,
  onToggleMediaSelect,
}: Props) {
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
  const rootGroups = useMemo(() => groupMediaItems(root.items, { sort, order }), [root.items, sort, order]);

  const toggleGroup = (groupKey: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(groupKey)) next.delete(groupKey);
      else next.add(groupKey);
      return next;
    });
  };

  return (
    <div className="folder-tree">
      {rootGroups.length > 0 && (
        <section className="folder-root-files">
          <h3>Root files</h3>
          <div className="video-group-list folder-video-group-list">
            {rootGroups.map((group) => {
              const groupRef = `root::${group.key}`;
              const isGroupCollapsed = collapsedGroups.has(groupRef);
              return (
                <section key={groupRef} className="video-group-section">
                  <GroupToggleHeader
                    expanded={!isGroupCollapsed}
                    onToggle={() => toggleGroup(groupRef)}
                    label={group.title}
                    count={`${group.items.length} photos`}
                    size="md"
                  />
                  {!isGroupCollapsed && (
                    <div className="video-grid video-grid-grouped">
                      {group.items.map((item) => (
                        <PhotoCard
                          key={item.id}
                          item={item}
                          selectionMode={selectionMode}
                          selected={selectedMediaKeys?.has(getMediaItemKey(item)) ?? false}
                          onToggleSelect={onToggleMediaSelect}
                        />
                      ))}
                    </div>
                  )}
                </section>
              );
            })}
          </div>
        </section>
      )}

      <ul className="folder-node-list">
        {root.children.map((node) => (
          <PhotoFolderNode
            key={node.path}
            node={node}
            expandedPaths={expandedPaths}
            onToggle={onToggle}
            sort={sort}
            order={order}
            selectionMode={selectionMode}
            selectedMediaKeys={selectedMediaKeys}
            onToggleMediaSelect={onToggleMediaSelect}
          />
        ))}
      </ul>
    </div>
  );
}
