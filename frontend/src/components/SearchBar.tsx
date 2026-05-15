type Props = {
  value: string;
  onChange: (value: string) => void;
};

export function SearchBar({ value, onChange }: Props) {
  return (
    <input
      className="search-input"
      type="search"
      placeholder="Search videos..."
      value={value}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}
