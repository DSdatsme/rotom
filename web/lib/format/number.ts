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

/** USD with precision that scales down for tiny LLM costs: $0.0004, $0.012, $3.40. */
export function formatUsd(v: number | null | undefined): string {
  if (v == null) return "—";
  if (v === 0) return "$0";
  if (v < 0.01) return `$${v.toFixed(4)}`;
  if (v < 1) return `$${v.toFixed(3)}`;
  return `$${v.toFixed(2)}`;
}

/** Span/LLM durations: "<1ms", "420ms", "3.21s", "1m 5s", "—". */
export function formatMs(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms < 1) return "<1ms";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(2)}s`;
  return `${Math.floor(ms / 60_000)}m ${Math.round((ms % 60_000) / 1000)}s`;
}
