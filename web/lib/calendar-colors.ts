/** Translucent background + text-color classes for event chips (rendered over the grid). */
export const PALETTE = [
  "bg-blue-500/15 text-blue-700 dark:text-blue-300",
  "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
  "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  "bg-fuchsia-500/15 text-fuchsia-700 dark:text-fuchsia-300",
  "bg-cyan-500/15 text-cyan-700 dark:text-cyan-300",
];

/**
 * Solid background classes, aligned index-for-index with PALETTE. Used for the legend
 * swatch, which needs a visible dot rather than a translucent chip background.
 */
export const SWATCH_PALETTE = [
  "bg-blue-500",
  "bg-emerald-500",
  "bg-amber-500",
  "bg-fuchsia-500",
  "bg-cyan-500",
];

/** Legend styling for an account whose fetch errored — a fixed red, not part of the
 * per-account palette (an errored account carries no event data to color-code). */
export const ERROR_SWATCH = "bg-red-500";
export const ERROR_TEXT = "text-red-500 dark:text-red-400";

/**
 * Assign each account a stable index into PALETTE / SWATCH_PALETTE by its position in a
 * sorted, deduplicated account list — not by hashing the account name in isolation. A
 * per-string hash can't guarantee distinct accounts land on distinct colors (e.g. this
 * repo's account names used to collapse onto 2 of 5 palette entries); indexing into a
 * shared sorted order guarantees no collisions as long as there are at most PALETTE.length
 * accounts. Callers should derive `accounts` once (e.g. from the full events list) and reuse
 * the same map everywhere a color is needed, so the legend and the event chips always agree.
 */
export function buildAccountColorMap(accounts: string[]): Record<string, number> {
  const sorted = [...new Set(accounts)].sort();
  const map: Record<string, number> = {};
  sorted.forEach((account, i) => {
    map[account] = i % PALETTE.length;
  });
  return map;
}
