type Props = {
  value: string;
  onChange: (value: string) => void;
};

export function SearchBar({ value, onChange }: Props) {
  return (
    <input
      className="search-input"
      value={value}
      onChange={(event) => onChange(event.target.value)}
      placeholder="Search videos..."
    />
  );
}

