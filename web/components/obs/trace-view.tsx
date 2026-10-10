"use client";

import { useMemo, useState, type CSSProperties } from "react";
import type { SpanRow, TraceDetail } from "@/lib/api";
import {
  buildWaterfall,
  CATEGORY_STYLE,
  CONTENT_KEYS,
  parseMessages,
  prettyPayload,
  spanCategory,
} from "@/lib/view/trace";
import { formatMs, formatTokens, formatUsd } from "@/lib/format/number";
import { Panel } from "@/components/ui/panel";
import { LogsPanel } from "@/components/logs-panel";
import { ChatMessages } from "@/components/obs/messages";
import { cn } from "@/lib/utils";

function Waterfall({
  spans,
  selected,
  onSelect,
}: {
  spans: SpanRow[];
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const { rows, totalMs } = useMemo(() => buildWaterfall(spans), [spans]);
  return (
    <div className="text-xs">
      <div className="flex border-b border-border px-3 py-1.5 text-[11px] text-faint">
        <div className="w-[38%] shrink-0">Span</div>
        <div className="flex flex-1 justify-between font-mono">
          <span>0</span>
          <span>{formatMs(totalMs / 2)}</span>
          <span>{formatMs(totalMs)}</span>
        </div>
      </div>
      {rows.map(({ span, depth, offsetPct, widthPct, category }) => {
        const isErr = span.status === "ERROR";
        const color = isErr ? "var(--destructive)" : CATEGORY_STYLE[category].color;
        const end = offsetPct + widthPct;
        // Keep the label off the bar: after it, else before it, else inside it (bar spans the track).
        const inside = end > 85 && offsetPct < 15;
        const labelStyle: CSSProperties =
          end <= 85
            ? { left: `calc(${end}% + 4px)` }
            : offsetPct >= 15
              ? { right: `calc(${100 - offsetPct}% + 4px)` }
              : { right: "4px" };
        return (
          <button
            key={span.span_id}
            type="button"
            onClick={() => onSelect(span.span_id)}
            className={cn(
              "flex w-full items-center px-3 py-1 text-left hover:bg-accent/50",
              selected === span.span_id && "bg-accent",
            )}
          >
            <div className="flex w-[38%] shrink-0 items-center gap-1.5 truncate" style={{ paddingLeft: depth * 14 }}>
              <span className="inline-block size-2 shrink-0 rounded-sm" style={{ background: color }} />
              <span className={cn("truncate font-mono", isErr && "text-destructive")}>{span.name}</span>
            </div>
            <div className="relative h-4 flex-1">
              <div
                className="absolute top-1 h-2 rounded-sm"
                style={{ left: `${offsetPct}%`, width: `${widthPct}%`, background: color, opacity: 0.85 }}
              />
              <span
                className={cn("absolute top-0 font-mono text-[10px]", inside ? "text-background" : "text-muted-foreground")}
                style={labelStyle}
              >
                {formatMs(span.duration_ms)}
              </span>
            </div>
          </button>
        );
      })}
    </div>
  );
}

function Inspector({ span }: { span: SpanRow }) {
  const cat = spanCategory(span);
  const a = span.attributes;
  const input = parseMessages(a["gen_ai.input.messages"]);
  const output = parseMessages(a["gen_ai.output.messages"]);
  const plain = Object.entries(a).filter(([k]) => !CONTENT_KEYS.has(k));
  const exceptions = span.events.filter((e) => e.name === "exception");
  return (
    <div className="space-y-4 p-4 text-sm">
      <div>
        <div className="text-xs text-muted-foreground">{CATEGORY_STYLE[cat].label}</div>
        <div className="font-mono font-semibold break-all">{span.name}</div>
        <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span>{formatMs(span.duration_ms)}</span>
          <span className={span.status === "ERROR" ? "text-destructive" : ""}>{span.status}</span>
          {span.model && <span className="font-mono">{span.model}</span>}
          {span.cost_usd != null && <span>{formatUsd(span.cost_usd)}</span>}
        </div>
        {span.status_message && <p className="mt-2 text-xs text-destructive">{span.status_message}</p>}
      </div>

      {cat === "llm" && (
        <div className="grid grid-cols-4 gap-2 text-center text-xs">
          {([["In", span.input_tokens], ["Out", span.output_tokens], ["Cached", span.cache_read_tokens],
             ["Thinking", span.reasoning_tokens]] as const).map(([label, v]) => (
            <div key={label} className="rounded border border-border px-2 py-1.5">
              <div className="text-faint">{label}</div>
              <div className="font-mono tabular-nums">{v != null ? formatTokens(v) : "—"}</div>
            </div>
          ))}
        </div>
      )}

      {input && (
        <section>
          <h3 className="mb-2 text-xs font-semibold text-muted-foreground uppercase">Input</h3>
          <ChatMessages messages={input} />
        </section>
      )}
      {output && (
        <section>
          <h3 className="mb-2 text-xs font-semibold text-muted-foreground uppercase">Output</h3>
          <ChatMessages messages={output} />
        </section>
      )}
      {a["gen_ai.tool.call.arguments"] != null && (
        <section>
          <h3 className="mb-2 text-xs font-semibold text-muted-foreground uppercase">Arguments</h3>
          <pre className="overflow-x-auto rounded bg-card-3 p-2 font-mono text-xs">{prettyPayload(a["gen_ai.tool.call.arguments"])}</pre>
        </section>
      )}
      {a["gen_ai.tool.call.result"] != null && (
        <section>
          <h3 className="mb-2 text-xs font-semibold text-muted-foreground uppercase">Result</h3>
          <pre className="max-h-80 overflow-auto rounded bg-card-3 p-2 font-mono text-xs whitespace-pre-wrap">{prettyPayload(a["gen_ai.tool.call.result"])}</pre>
        </section>
      )}
      {exceptions.map((e, i) => (
        <section key={i}>
          <h3 className="mb-2 text-xs font-semibold text-destructive uppercase">Exception</h3>
          <pre className="max-h-80 overflow-auto rounded border-l-2 border-destructive/40 bg-destructive/8 p-2 font-mono text-xs whitespace-pre-wrap text-destructive">
            {String(e.attributes["exception.stacktrace"] ?? e.attributes["exception.message"] ?? "")}
          </pre>
        </section>
      ))}
      <section>
        <h3 className="mb-2 text-xs font-semibold text-muted-foreground uppercase">Attributes</h3>
        <table className="w-full text-xs">
          <tbody className="divide-y divide-border/60">
            {plain.map(([k, v]) => (
              <tr key={k}>
                <td className="py-1 pr-3 align-top font-mono text-muted-foreground">{k}</td>
                <td className="py-1 font-mono break-all">{typeof v === "string" ? v : JSON.stringify(v)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

/** Waterfall + span inspector + the trace's logs. `compact` hides logs (run detail has its own). */
export function TraceView({ detail, compact = false }: { detail: TraceDetail; compact?: boolean }) {
  const firstInteresting =
    detail.spans.find((s) => s.status === "ERROR") ?? detail.spans.find((s) => s.operation === "chat") ?? detail.spans[0];
  const [selectedId, setSelectedId] = useState<string | null>(firstInteresting?.span_id ?? null);
  const selected = detail.spans.find((s) => s.span_id === selectedId) ?? null;

  return (
    <div className="space-y-4">
      <div className="grid gap-4 xl:grid-cols-[3fr_2fr]">
        <Panel title="Waterfall" sub={`${detail.spans.length} spans`} noPad>
          <Waterfall spans={detail.spans} selected={selectedId} onSelect={setSelectedId} />
        </Panel>
        <Panel title="Span" noPad className="xl:sticky xl:top-4 xl:max-h-[calc(100vh-2rem)] xl:overflow-auto">
          {selected ? <Inspector span={selected} /> : <p className="p-4 text-sm text-muted-foreground">Select a span.</p>}
        </Panel>
      </div>
      {!compact && (
        <LogsPanel logs={detail.logs} title="Logs in this trace" showLogger showRunId={false} className="max-h-[420px]" />
      )}
    </div>
  );
}
