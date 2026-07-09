// Shared display formatters. Kept dependency-free so any client component can use them.

/**
 * Format a [0,1] ratio as a percentage string.
 * Guards against NaN/undefined (returns `dash`) and clamps out-of-range values
 * so a bad backend number can never render as "NaN%" or "7700%".
 */
export function pct(
  v: number | null | undefined,
  opts: { digits?: number; dash?: string } = {},
): string {
  const { digits = 0, dash = "—" } = opts;
  if (typeof v !== "number" || Number.isNaN(v)) return dash;
  const clamped = Math.min(1, Math.max(0, v));
  return `${(clamped * 100).toFixed(digits)}%`;
}
