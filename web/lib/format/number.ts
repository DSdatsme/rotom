/** Compact token counts: 742 → "742", 1.5K, 2.50M. */
export function formatTokens(n: number): string {
  if (n >= 1e6) return (n / 1e6).toFixed(2) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
  return String(n);
}

/** Locale-grouped integer: 1284 → "1,284". */
export function formatInt(n: number): string {
  return n.toLocaleString("en-US");
}

/** Milliseconds → seconds string: 420 → "0.42s". */
export function formatLatencyMs(ms: number): string {
  return (ms / 1000).toFixed(2) + "s";
}
