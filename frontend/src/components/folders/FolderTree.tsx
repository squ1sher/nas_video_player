import { useMemo, useState } from "react";

import type { SortField, SortOrder } from "../../api/client";
import type { WatchProgress } from "../../types/video";
import type { FolderTreeNode } from "../../utils/buildFolderTree";
import { groupVideos } from "../../utils/groupVideos";
import { FolderNode } from "./FolderNode";
import { VideoCard } from "../VideoCard";

type Props = {
  root: FolderTreeNode;
  expandedPaths: Set<string>;
  onToggle: (path: string) => void;
  progressByVideoId: Record<number, WatchProgress | undefined>;
  sort: SortField;
  order: SortOrder;
  selectionMode?: boolean;
  selectedVideoIds?: Set<number>;
  onToggleVideoSelect?: (videoId: number) => void;
};

export function FolderTree({
  root,
  expandedPaths,
  onToggle,
  progressByVideoId,
  sort,
  order,
  selectionMode = false,
  selectedVideoIds,
  onToggleVideoSelect,
}: Props) {
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
  const rootGroups = useMemo(() => groupVideos(root.videos, { sort, order }), [root.videos, sort, order]);

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
        </section>
      )}

      <ul className="folder-node-list">
        {root.children.map((node) => (
          <FolderNode
            key={node.path}
            node={node}
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
    </div>
  );
}

