/**
 * Shared utilities for observability UI components.
 * Kept framework-agnostic (no React imports) so they can be used in both
 * server components and client components.
 */

/** Format a token count with locale grouping (e.g. 1,234). */
export function formatTokens(num: number): string {
  return new Intl.NumberFormat().format(num);
}

/**
 * Normalize a server datetime string into a form `new Date()` parses as UTC.
 *
 * Our backend emits three shapes, and the naive `ts + "Z"` trick breaks two of them:
 *   - `2026-06-13T12:30:00.024446`        (naive, no tz)      → append Z
 *   - `2026-06-10T08:42:00.742717+00:00`  (explicit offset)   → leave as-is (Z would dupe tz → Invalid Date)
 *   - `2026-06-13 12:30:00`               (space-separated)   → swap space for T, then append Z
 *   - `2026-06-11`                        (date-only bucket)  → leave as-is (Date parses as UTC midnight)
 */
export function normalizeTs(ts: string): string {
  let s = ts.trim();
  // Space-separated SQLite datetime → ISO `T` separator
  if (s.includes(" ") && !s.includes("T")) s = s.replace(" ", "T");
  // Date-only bucket: parsed as UTC midnight; appending Z would make it invalid
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return s;
  // Already carries a timezone (trailing Z or ±HH:MM offset) → don't touch it
  if (/[zZ]$/.test(s) || /[+-]\d{2}:?\d{2}$/.test(s)) return s;
  // Naive datetime → assume UTC
  return `${s}Z`;
}

/** Format a UTC ISO datetime string as a local time string (HH:MM:SS). */
export function formatTs(ts: string | null): string {
  if (!ts) return "";
  const d = new Date(normalizeTs(ts));
  if (isNaN(d.getTime())) return "";
  return d.toLocaleTimeString(undefined, {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

/** Format a datetime string as a local date (no time) — for daily buckets. */
export function formatDate(ts: string | null): string {
  if (!ts) return "";
  const d = new Date(normalizeTs(ts));
  if (isNaN(d.getTime())) return ts;
  return new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(d);
}

/** Format a datetime string as a compact, sortable local datetime: `YYYY-MM-DD HH:MM:SS`. */
export function formatDateTimeSeconds(ts: string | null): string {
  if (!ts) return "";
  const d = new Date(normalizeTs(ts));
  if (isNaN(d.getTime())) return ts;
  const p = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ` +
    `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
  );
}

/** Format a datetime string as a local date + time (medium / short). */
export function formatDateTime(ts: string | null): string {
  if (!ts) return "";
  const d = new Date(normalizeTs(ts));
  if (isNaN(d.getTime())) return ts;
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(d);
}

/** Tailwind text colour class for a log level (token-based). */
export function levelColor(level: string): string {
  switch (level?.toUpperCase()) {
    case "ERROR":
    case "CRITICAL":
      return "text-destructive";
    case "WARNING":
      return "text-warning";
    case "DEBUG":
      return "text-faint";
    default:
      return "text-brand";
  }
}

/**
 * Per-row level accent. Rows all share one container background; level is
 * signalled only by a thin inset left rail (no fill block) + the colored level
 * label — matching the mock's `.log-row` treatment.
 */
export function levelBg(level: string): string {
  switch (level?.toUpperCase()) {
    case "ERROR":
    case "CRITICAL":
      return "shadow-[inset_2px_0_0_var(--destructive)]";
    case "WARNING":
      return "shadow-[inset_2px_0_0_var(--warning)]";
    default:
      return "";
  }
}

/** Format a relative time string from an ISO date string. */
export function formatRelativeTime(dateString: string): string {
  const date = new Date(normalizeTs(dateString));
  if (isNaN(date.getTime())) return "";
  const now = new Date();
  const diffInSeconds = Math.floor((now.getTime() - date.getTime()) / 1000);
  if (diffInSeconds < 60) return "just now";
  if (diffInSeconds < 3600) return `${Math.floor(diffInSeconds / 60)}m ago`;
  if (diffInSeconds < 86400) return `${Math.floor(diffInSeconds / 3600)}h ago`;
  return `${Math.floor(diffInSeconds / 86400)}d ago`;
}

/** Parse a JSONL log blob (e.g. from RunDetail.logs) into structured rows. */
export interface ParsedLog {
  ts?: string;
  level?: string;
  logger?: string;
  msg?: string;
  exc_info?: string;
  run_id?: string | number | null;
  [key: string]: unknown;
}

export function parseJsonlLogs(raw: string): ParsedLog[] {
  if (!raw) return [];
  return raw
    .split("\n")
    .filter((l) => l.trim().length > 0)
    .map((line) => {
      try {
        return JSON.parse(line) as ParsedLog;
      } catch {
        return { msg: line, level: "INFO" };
      }
    });
}

/** Compute a human-readable duration string for a run. */
export function computeDuration(
  startedAt: string | null,
  finishedAt: string | null,
  status: string,
): string {
  if (startedAt && finishedAt) {
    const start = new Date(normalizeTs(startedAt));
    const end = new Date(normalizeTs(finishedAt));
    const diffMs = end.getTime() - start.getTime();
    if (diffMs < 1000) return `${diffMs}ms`;
    if (diffMs < 60000) return `${(diffMs / 1000).toFixed(1)}s`;
    const mins = Math.floor(diffMs / 60000);
    const secs = Math.floor((diffMs % 60000) / 1000);
    return `${mins}m ${secs}s`;
  }
  if (status === "running" && startedAt) {
    const start = new Date(normalizeTs(startedAt));
    const secs = Math.floor((new Date().getTime() - start.getTime()) / 1000);
    return `${secs}s`;
  }
  return "—";
}
