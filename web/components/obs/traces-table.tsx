import Link from "next/link";
import type { RunStatus, TraceSummary } from "@/lib/api";
import { RUN_STATUS } from "@/lib/view/run";
import { TRACE_TYPE_LABEL } from "@/lib/view/trace";
import { toneDot } from "@/lib/tone";
import { relativeTime } from "@/lib/format/datetime";
import { formatMs, formatTokens, formatUsd } from "@/lib/format/number";
import { normalizeTs } from "@/lib/obs-utils";

function statusDot(t: TraceSummary): string {
  if (t.run_status) return toneDot[RUN_STATUS[t.run_status as RunStatus]?.tone ?? "muted"];
  if (t.status === "ERROR") return toneDot.danger;
  return t.error_count ? toneDot.warning : toneDot.success;
}

export function TracesTable({ traces, now }: { traces: TraceSummary[]; now: number }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-border text-xs tracking-wider text-muted-foreground uppercase">
          <tr>
            <th className="px-4 py-2 font-medium">Trace</th>
            <th className="px-4 py-2 font-medium">Type</th>
            <th className="px-4 py-2 font-medium">Started</th>
            <th className="px-4 py-2 text-right font-medium">Duration</th>
            <th className="px-4 py-2 text-right font-medium">Spans</th>
            <th className="px-4 py-2 text-right font-medium">LLM</th>
            <th className="px-4 py-2 text-right font-medium">Tokens</th>
            <th className="px-4 py-2 text-right font-medium">Cost</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/60">
          {traces.map((t) => (
            <tr key={t.trace_id} className="hover:bg-accent/40">
              <td className="px-4 py-2">
                <Link href={`/observability/traces/${t.trace_id}`} className="flex items-center gap-2 font-medium hover:underline">
                  <span className={`inline-block size-2 shrink-0 rounded-full ${statusDot(t)}`} />
                  <span className="truncate font-mono text-xs">{t.root_name}</span>
                  {t.error_count > 0 && <span className="text-xs text-destructive">{t.error_count} err</span>}
                </Link>
              </td>
              <td className="px-4 py-2 text-xs text-muted-foreground">{TRACE_TYPE_LABEL[t.trace_type]}</td>
              <td className="px-4 py-2 text-xs text-muted-foreground">{relativeTime(normalizeTs(t.start_time), now)}</td>
              <td className="mono px-4 py-2 text-right text-xs">{formatMs(t.duration_ms)}</td>
              <td className="mono px-4 py-2 text-right text-xs">{t.span_count}</td>
              <td className="mono px-4 py-2 text-right text-xs">{t.llm_calls || "—"}</td>
              <td className="mono px-4 py-2 text-right text-xs">
                {t.input_tokens + t.output_tokens ? formatTokens(t.input_tokens + t.output_tokens) : "—"}
              </td>
              <td className="mono px-4 py-2 text-right text-xs">{formatUsd(t.cost_usd)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
