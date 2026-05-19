import type { VideoListItem } from "../types/video";

export type FolderTreeNode = {
  name: string;
  path: string;
  children: FolderTreeNode[];
  videos: VideoListItem[];
  totalVideoCount: number;
  directVideoCount: number;
};

type MutableFolderTreeNode = FolderTreeNode & {
  childrenMap: Map<string, MutableFolderTreeNode>;
};

function createNode(name: string, path: string): MutableFolderTreeNode {
  return {
    name,
    path,
    children: [],
    childrenMap: new Map<string, MutableFolderTreeNode>(),
    videos: [],
    totalVideoCount: 0,
    directVideoCount: 0,
  };
}

function normalizeFolderPath(folderPath: string | null | undefined): string {
  return (folderPath ?? "").replace(/\\/g, "/").split("/").filter(Boolean).join("/");
}

function toImmutable(node: MutableFolderTreeNode): FolderTreeNode {
  const children = [...node.childrenMap.values()]
    .sort((a, b) => a.name.localeCompare(b.name, "en", { sensitivity: "base" }))
    .map(toImmutable);

  const directVideoCount = node.videos.length;
  const childrenVideoCount = children.reduce((acc, child) => acc + child.totalVideoCount, 0);

  return {
    name: node.name,
    path: node.path,
    children,
    videos: node.videos,
    directVideoCount,
    totalVideoCount: directVideoCount + childrenVideoCount,
  };
}

export function buildFolderTree(videos: VideoListItem[]): FolderTreeNode {
  const root = createNode("", "");

  for (const video of videos) {
    const folderPath = normalizeFolderPath(video.folder_path);
    if (!folderPath) {
      root.videos.push(video);
      continue;
    }

    const parts = folderPath.split("/");
    let current = root;
    let currentPath = "";

    for (const part of parts) {
      currentPath = currentPath ? `${currentPath}/${part}` : part;
      let child = current.childrenMap.get(part);
      if (!child) {
        child = createNode(part, currentPath);
        current.childrenMap.set(part, child);
      }
      current = child;
    }

    current.videos.push(video);
  }

  return toImmutable(root);
}

