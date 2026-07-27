import type { UnifiedMediaItem } from "../types/video";

export type MediaFolderTreeNode = {
  name: string;
  path: string;
  children: MediaFolderTreeNode[];
  items: UnifiedMediaItem[];
  totalItemCount: number;
  directItemCount: number;
};

type MutableMediaFolderTreeNode = MediaFolderTreeNode & {
  childrenMap: Map<string, MutableMediaFolderTreeNode>;
};

function createNode(name: string, path: string): MutableMediaFolderTreeNode {
  return {
    name,
    path,
    children: [],
    childrenMap: new Map<string, MutableMediaFolderTreeNode>(),
    items: [],
    totalItemCount: 0,
    directItemCount: 0,
  };
}

function normalizeFolderPath(folderPath: string | null | undefined): string {
  return (folderPath ?? "").replace(/\\/g, "/").split("/").filter(Boolean).join("/");
}

function toImmutable(node: MutableMediaFolderTreeNode): MediaFolderTreeNode {
  const children = [...node.childrenMap.values()]
    .sort((a, b) => a.name.localeCompare(b.name, "en", { sensitivity: "base" }))
    .map(toImmutable);

  const directItemCount = node.items.length;
  const childrenItemCount = children.reduce((acc, child) => acc + child.totalItemCount, 0);

  return {
    name: node.name,
    path: node.path,
    children,
    items: node.items,
    directItemCount,
    totalItemCount: directItemCount + childrenItemCount,
  };
}

export function buildMediaFolderTree(items: UnifiedMediaItem[]): MediaFolderTreeNode {
  const root = createNode("", "");

  for (const item of items) {
    const folderPath = normalizeFolderPath(item.folder_path);
    if (!folderPath) {
      root.items.push(item);
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

    current.items.push(item);
  }

  return toImmutable(root);
}
