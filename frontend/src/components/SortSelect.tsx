import type { SortField, SortOrder } from "../api/client";

export type SortOption = {
  label: string;
  sort: SortField;
};

export const SORT_OPTIONS: SortOption[] = [
  { label: "Date", sort: "file_modified_at" },
  { label: "Duration", sort: "duration" },
  { label: "File size", sort: "size" },
];

type Props = {
  sort: SortField;
  order: SortOrder;
  onChange: (sort: SortField, order: SortOrder) => void;
};

export function SortSelect({ sort, order, onChange }: Props) {
  const currentSort = SORT_OPTIONS.find((option) => option.sort === sort)?.sort ?? "file_modified_at";

  function handleSortChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const nextSort = e.target.value as SortField;
    onChange(nextSort, order);
  }

  function toggleOrder() {
    onChange(sort, order === "desc" ? "asc" : "desc");
  }

  return (
    <div className="sort-controls">
      <select value={currentSort} onChange={handleSortChange}>
        {SORT_OPTIONS.map((opt) => (
          <option key={opt.sort} value={opt.sort}>
            {opt.label}
          </option>
        ))}
      </select>
      <button type="button" className="sort-order-toggle" onClick={toggleOrder}>
        {order === "desc" ? "Descending" : "Ascending"}
      </button>
    </div>
  );
}
