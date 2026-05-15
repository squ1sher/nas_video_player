type Status = "direct_play" | "may_not_play" | "needs_conversion" | null | undefined;

type Props = {
  status: Status;
  reason?: string | null;
  showTooltip?: boolean;
};

const LABELS: Record<NonNullable<Status>, string> = {
  direct_play: "✓ Direct play",
  may_not_play: "⚠ May not play",
  needs_conversion: "✗ Needs conversion",
};

const CSS_CLASS: Record<NonNullable<Status>, string> = {
  direct_play: "compat-badge compat-direct",
  may_not_play: "compat-badge compat-warn",
  needs_conversion: "compat-badge compat-error",
};

export function CompatibilityBadge({ status, reason, showTooltip = false }: Props) {
  if (!status) return null;
  return (
    <span
      className={CSS_CLASS[status]}
      title={showTooltip && reason ? reason : undefined}
    >
      {LABELS[status]}
    </span>
  );
}
