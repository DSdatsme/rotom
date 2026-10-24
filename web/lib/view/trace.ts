import type { SpanRow, TraceType } from "@/lib/api";
import { normalizeTs } from "@/lib/obs-utils";

export type SpanCategory = "run" | "agent" | "llm" | "tool" | "http" | "step";

export const CATEGORY_STYLE: Record<SpanCategory, { label: string; color: string }> = {
  run: { label: "Run", color: "var(--slate)" },
  agent: { label: "Agent", color: "var(--chart-2)" },
  llm: { label: "LLM", color: "var(--brand)" },
  tool: { label: "Tool", color: "var(--chart-3)" },
  http: { label: "API", color: "var(--chart-4)" },
  step: { label: "Step", color: "var(--muted-foreground)" },
};

export const TRACE_TYPE_LABEL: Record<TraceType, string> = { run: "Run", chat: "Chat", http: "API", other: "Other" };

/** Attributes rendered as content blocks, not in the attribute table. */
export const CONTENT_KEYS = new Set([
  "gen_ai.input.messages",
  "gen_ai.output.messages",
  "gen_ai.tool.call.arguments",
  "gen_ai.tool.call.result",
]);

export function spanCategory(s: SpanRow): SpanCategory {
  if (s.attributes["rotom.run.kind"] != null) return "run";
  if (s.operation === "invoke_agent") return "agent";
  if (s.operation === "chat") return "llm";
  if (s.operation === "execute_tool") return "tool";
  if (s.span_kind === "SERVER") return "http";
  return "step";
}

export interface WaterfallRow {
  span: SpanRow;
  depth: number;
  offsetPct: number;
  widthPct: number;
  category: SpanCategory;
}

const ms = (iso: string) => Date.parse(normalizeTs(iso));

/**
 * Depth-first span tree ordered by start time, with bar geometry relative to the trace.
 * Spans whose parent isn't present (root not exported yet) are rendered as roots.
 */
export function buildWaterfall(spans: SpanRow[]): { rows: WaterfallRow[]; totalMs: number } {
  if (spans.length === 0) return { rows: [], totalMs: 0 };
  const ids = new Set(spans.map((s) => s.span_id));
  const children = new Map<string, SpanRow[]>();
  const roots: SpanRow[] = [];
  for (const s of spans) {
    if (s.parent_span_id && ids.has(s.parent_span_id)) {
      const list = children.get(s.parent_span_id) ?? [];
      list.push(s);
      children.set(s.parent_span_id, list);
    } else {
      roots.push(s);
    }
  }
  const start = Math.min(...spans.map((s) => ms(s.start_time)));
  const end = Math.max(...spans.map((s) => ms(s.end_time)));
  const totalMs = Math.max(end - start, 1);
  const byStart = (a: SpanRow, b: SpanRow) => ms(a.start_time) - ms(b.start_time);
  const rows: WaterfallRow[] = [];
  const walk = (s: SpanRow, depth: number) => {
    rows.push({
      span: s,
      depth,
      category: spanCategory(s),
      offsetPct: ((ms(s.start_time) - start) / totalMs) * 100,
      widthPct: Math.max((s.duration_ms / totalMs) * 100, 0.4),
    });
    (children.get(s.span_id) ?? []).sort(byStart).forEach((c) => walk(c, depth + 1));
  };
  roots.sort(byStart).forEach((r) => walk(r, 0));
  return { rows, totalMs };
}

export interface ChatMessage {
  role: string;
  content: string;
  tool_calls?: { name: string; args: unknown }[];
}

/** Captured content attributes are JSON strings; returns null when absent or unparseable. */
export function parseMessages(raw: unknown): ChatMessage[] | null {
  if (typeof raw !== "string") return null;
  try {
    const v = JSON.parse(raw);
    return Array.isArray(v) ? (v as ChatMessage[]) : null;
  } catch {
    return null;
  }
}

/** Pretty-print a captured JSON payload; falls back to the raw string. */
export function prettyPayload(raw: unknown): string {
  if (typeof raw !== "string") return JSON.stringify(raw, null, 2);
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return raw;
  }
}
