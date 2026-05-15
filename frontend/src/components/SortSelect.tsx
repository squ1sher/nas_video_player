import type { SortField, SortOrder } from "../api/client";

export type SortOption = {
  label: string;
  sort: SortField;
  order: SortOrder;
};

export const SORT_OPTIONS: SortOption[] = [
  { label: "Newest first", sort: "created_at", order: "desc" },
  { label: "Oldest first", sort: "created_at", order: "asc" },
  { label: "Title A-Z", sort: "title", order: "asc" },
  { label: "Title Z-A", sort: "title", order: "desc" },
  { label: "Duration", sort: "duration", order: "desc" },
  { label: "File size", sort: "size", order: "desc" },
];

type Props = {
  sort: SortField;
  order: SortOrder;
  onChange: (sort: SortField, order: SortOrder) => void;
};

export function SortSelect({ sort, order, onChange }: Props) {
  const currentValue = SORT_OPTIONS.findIndex(
    (o) => o.sort === sort && o.order === order
  );
  const selectedIndex = currentValue >= 0 ? currentValue : 0;

  function handleChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const idx = parseInt(e.target.value, 10);
    const opt = SORT_OPTIONS[idx];
    if (opt) onChange(opt.sort, opt.order);
  }

  return (
    <div className="sort-controls">
      <select value={selectedIndex} onChange={handleChange}>
        {SORT_OPTIONS.map((opt, i) => (
          <option key={i} value={i}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  );
}
