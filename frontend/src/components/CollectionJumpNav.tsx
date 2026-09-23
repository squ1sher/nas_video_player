export type JumpNavItem = {
  id: string;
  label: string;
};

type Props = {
  items: JumpNavItem[];
  onCollapseAll?: () => void;
};

/**
 * Right-hand rail shown on every collection page (grouped browser, folder
 * trees, playlist detail): jump links to each top-level group that's been
 * scrolled past, a "back to top" shortcut, and a "collapse all" action.
 */
export function CollectionJumpNav({ items, onCollapseAll }: Props) {
  if (items.length < 2 && !onCollapseAll) return null;

  const scrollToTop = () => window.scrollTo({ top: 0, behavior: "smooth" });
  const scrollToItem = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <aside className="collection-jump-nav" aria-label="Jump to group">
      <div className="collection-jump-actions">
        <button type="button" className="collection-jump-action-btn" onClick={scrollToTop} title="Back to top">
          ⤒ Top
        </button>
        {onCollapseAll ? (
          <button type="button" className="collection-jump-action-btn" onClick={onCollapseAll} title="Collapse all groups">
            ▲ Collapse all
          </button>
        ) : null}
      </div>
      {items.length > 1 ? (
        <div className="collection-jump-list">
          {items.map((item) => (
            <button
              key={item.id}
              type="button"
              className="collection-jump-item"
              onClick={() => scrollToItem(item.id)}
              title={item.label}
            >
              {item.label}
            </button>
          ))}
        </div>
      ) : null}
    </aside>
  );
}
