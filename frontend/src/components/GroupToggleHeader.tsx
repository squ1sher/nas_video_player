import type { ReactNode } from "react";

type Size = "lg" | "md";

type Props = {
  /** Whether the group's contents are currently shown. */
  expanded: boolean;
  /** Primary text of the header (folder / date-bucket / playlist-group name). */
  label: ReactNode;
  /** Secondary right-aligned text, e.g. item count. */
  count?: ReactNode;
  onToggle: () => void;
  /** Optional element rendered before the caret, e.g. a selection checkbox. */
  leading?: ReactNode;
  /** "lg" for top-level groups (years, sources), "md" for nested ones. */
  size?: Size;
  /** DOM id used as a scroll target for the collection jump nav. */
  id?: string;
};

/**
 * Single consistent collapse/expand header used across every page that
 * displays grouped media collections (grouped browser, folder trees,
 * playlist detail). Keeps the caret glyph, spacing and typography identical
 * everywhere so the pages don't look like separate UIs.
 */
export function GroupToggleHeader({ expanded, label, count, onToggle, leading, size = "md", id }: Props) {
  return (
    <div id={id} className={`group-toggle-header group-toggle-header--${size}`}>
      {leading}
      <button type="button" className="group-toggle-header-btn" onClick={onToggle}>
        <span className="group-toggle-caret">{expanded ? "▼" : "▶"}</span>
        <span className="group-toggle-label">{label}</span>
        {count !== undefined ? <span className="group-toggle-count">{count}</span> : null}
      </button>
    </div>
  );
}
