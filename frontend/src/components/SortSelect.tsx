type SortField = "title" | "created_at" | "duration" | "size";
type SortOrder = "asc" | "desc";

type Props = {
  sort: SortField;
  order: SortOrder;
  onSortChange: (value: SortField) => void;
  onOrderChange: (value: SortOrder) => void;
};

export function SortSelect({ sort, order, onSortChange, onOrderChange }: Props) {
  return (
    <div className="sort-controls">
      <select value={sort} onChange={(event) => onSortChange(event.target.value as SortField)}>
        <option value="title">Title</option>
        <option value="created_at">Created</option>
        <option value="duration">Duration</option>
        <option value="size">Size</option>
      </select>
      <select value={order} onChange={(event) => onOrderChange(event.target.value as SortOrder)}>
        <option value="asc">Asc</option>
        <option value="desc">Desc</option>
      </select>
    </div>
  );
}

