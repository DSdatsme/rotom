import type { Tone } from "@/lib/view/email";

export function levelTone(level: string): Tone {
  switch (level.toUpperCase()) {
    case "DEBUG":
      return "muted";
    case "INFO":
      return "brand";
    case "WARNING":
      return "warning";
    case "ERROR":
    case "CRITICAL":
      return "danger";
    default:
      return "muted";
  }
}

export interface ParsedLog {
  level: string;
  msg: string;
  ts?: string;
  logger?: string;
  kind?: string;
  [k: string]: unknown;
}

/** Parse a JSONL log blob into rows; skip blank/unparseable lines. */
export function parseRunLogs(jsonl: string | null): ParsedLog[] {
  if (!jsonl) return [];
  const out: ParsedLog[] = [];
  for (const line of jsonl.split("\n")) {
    const t = line.trim();
    if (!t) continue;
    try {
      const obj = JSON.parse(t);
      if (obj && typeof obj === "object") out.push(obj as ParsedLog);
    } catch {
      /* skip non-JSON line */
    }
  }
  return out;
}

/** Parse a LogEntry.extra JSON string → object, or null. */
export function parseExtra(extra: string): Record<string, unknown> | null {
  if (!extra) return null;
  try {
    const obj = JSON.parse(extra);
    return obj && typeof obj === "object" ? (obj as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}
