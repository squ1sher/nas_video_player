import { useMemo, useState } from "react";

import type { SortField, SortOrder } from "../../api/client";
import type { WatchProgress } from "../../types/video";
import type { FolderTreeNode } from "../../utils/buildFolderTree";
import { groupVideos } from "../../utils/groupVideos";
import { VideoCard } from "../VideoCard";

type Props = {
  node: FolderTreeNode;
  expandedPaths: Set<string>;
  onToggle: (path: string) => void;
  progressByVideoId: Record<number, WatchProgress | undefined>;
  sort: SortField;
  order: SortOrder;
  selectionMode?: boolean;
  selectedVideoIds?: Set<number>;
  onToggleVideoSelect?: (videoId: number) => void;
};

function folderMeta(node: FolderTreeNode): string {
  const parts: string[] = [];
  if (node.children.length > 0) {
    parts.push(`${node.children.length} folder${node.children.length === 1 ? "" : "s"}`);
  }
  parts.push(`${node.totalVideoCount} video${node.totalVideoCount === 1 ? "" : "s"}`);
  return parts.join(" - ");
}

export function FolderNode({
  node,
  expandedPaths,
  onToggle,
  progressByVideoId,
  sort,
  order,
  selectionMode = false,
  selectedVideoIds,
  onToggleVideoSelect,
}: Props) {
  const isExpanded = expandedPaths.has(node.path);
  const canExpand = node.children.length > 0 || node.videos.length > 0;
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
  const groups = useMemo(() => groupVideos(node.videos, { sort, order }), [node.videos, sort, order]);

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
      <div className="folder-row">
        {canExpand ? (
          <button className="folder-toggle" onClick={() => onToggle(node.path)}>{isExpanded ? "v" : ">"}</button>
        ) : (
          <span className="folder-toggle-placeholder" />
        )}
        <button className="folder-label" onClick={() => onToggle(node.path)}>
          <span className="folder-node-icon">DIR</span>
          <span className="folder-name">{node.name}</span>
          <span className="folder-count">{folderMeta(node)}</span>
        </button>
      </div>

      {isExpanded && (
        <div className="folder-children-wrap">
          {node.children.length > 0 && (
            <ul className="folder-node-list">
              {node.children.map((child) => (
                <FolderNode
                  key={child.path}
                  node={child}
                  expandedPaths={expandedPaths}
                  onToggle={onToggle}
                  progressByVideoId={progressByVideoId}
                  sort={sort}
                  order={order}
                  selectionMode={selectionMode}
                  selectedVideoIds={selectedVideoIds}
                  onToggleVideoSelect={onToggleVideoSelect}
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
                    <button className="video-group-header video-group-toggle" onClick={() => toggleGroup(groupRef)}>
                      <span>{isGroupCollapsed ? ">" : "v"}</span>
                      <span>{group.title} - {group.videos.length} videos</span>
                    </button>
                    {!isGroupCollapsed && (
                      <div className="video-grid video-grid-grouped">
                        {group.videos.map((video) => (
                          <VideoCard
                            key={video.id}
                            video={video}
                            progress={progressByVideoId[video.id]}
                            selectionMode={selectionMode}
                            selected={selectedVideoIds?.has(video.id) ?? false}
                            onToggleSelect={onToggleVideoSelect}
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



