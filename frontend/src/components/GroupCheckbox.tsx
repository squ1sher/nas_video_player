import { useEffect, useRef } from "react";

interface GroupCheckboxProps {
  checked: boolean;
  indeterminate: boolean;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
  label?: string;
}

/**
 * A checkbox that supports the indeterminate ("partial") state.
 * Used in group headers when selection mode is active.
 */
export function GroupCheckbox({ checked, indeterminate, disabled, onChange, label }: GroupCheckboxProps) {
  const ref = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (ref.current) {
      ref.current.indeterminate = indeterminate;
    }
  }, [indeterminate, checked]);

  return (
    <input
      ref={ref}
      type="checkbox"
      className="group-select-checkbox"
      checked={checked}
      disabled={disabled}
      aria-label={label}
      onChange={(e) => {
        e.stopPropagation();
        onChange(e.target.checked);
      }}
      onClick={(e) => e.stopPropagation()}
    />
  );
}

