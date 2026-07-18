import { Hash, ArrowDown, ArrowUp, Gauge } from "lucide-react";

import { getUsage } from "@/lib/api";
import { usageKpis } from "@/lib/view/usage";
import { formatTokens as compactTokens } from "@/lib/format/number";
import { formatDate, formatTokens } from "@/lib/obs-utils";
import { TokensChart } from "@/components/tokens-chart";
import { Panel } from "@/components/ui/panel";

export const dynamic = "force-dynamic";

function Kpi({
  label,
  value,
  sub,
  icon: IconCmp,
}: {
  label: string;
  value: string;
  sub: string;
  icon: typeof Hash;
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <IconCmp className="size-3.5" /> {label}
      </div>
      <div className="mt-2 text-2xl font-semibold tabular-nums">{value}</div>
      <div className="mt-0.5 text-xs text-faint">{sub}</div>
    </div>
  );
}

export default async function ObservabilityPage() {
  const usage = await getUsage(14);
  const kpis = usageKpis(usage);
  const inputPct = kpis.totalTokens ? Math.round((kpis.input / kpis.totalTokens) * 100) : 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Observability</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Token usage across all models <span className="mono text-faint">(Last 14 days)</span>
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Kpi label="Total tokens" value={compactTokens(kpis.totalTokens)} sub="14-day window" icon={Hash} />
        <Kpi label="Input" value={compactTokens(kpis.input)} sub={`${inputPct}% of total`} icon={ArrowDown} />
        <Kpi label="Output" value={compactTokens(kpis.output)} sub={`${100 - inputPct}% of total`} icon={ArrowUp} />
        <Kpi label="Avg latency" value={`${(kpis.avgLatencyMs / 1000).toFixed(2)}s`} sub="across runs" icon={Gauge} />
      </div>

      <Panel title="Tokens over time" sub="Stacked by model">
        <TokensChart usage={usage} />
      </Panel>

      <Panel title="Usage log" sub="Per-run token accounting" noPad>
        <table className="w-full text-left text-sm">
          <thead className="border-b border-border text-xs tracking-wider text-muted-foreground uppercase">
            <tr>
              <th className="px-4 py-2 font-medium">Date</th>
              <th className="px-4 py-2 font-medium">Purpose</th>
              <th className="px-4 py-2 font-medium">Model</th>
              <th className="px-4 py-2 text-right font-medium">Input</th>
              <th className="px-4 py-2 text-right font-medium">Output</th>
              <th className="px-4 py-2 text-right font-medium">Avg Latency</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/60">
            {usage.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-muted-foreground">
                  No usage data recorded yet.
                </td>
              </tr>
            ) : (
              usage.map((row, i) => (
                <tr key={i} className="transition-colors hover:bg-accent/40">
                  <td className="mono px-4 py-2 text-xs whitespace-nowrap">{formatDate(row.day)}</td>
                  <td className="px-4 py-2">
                    {row.purpose ? (
                      <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-soft px-2 py-0.5 text-xs font-medium text-brand">
                        {row.purpose} <span className="opacity-60">#{row.run_id}</span>
                      </span>
                    ) : (
                      <span className="text-xs text-faint italic">adhoc</span>
                    )}
                  </td>
                  <td className="mono px-4 py-2 text-xs">{row.model}</td>
                  <td className="mono px-4 py-2 text-right text-xs">{formatTokens(row.input_tokens)}</td>
                  <td className="mono px-4 py-2 text-right text-xs">{formatTokens(row.output_tokens)}</td>
                  <td className="mono px-4 py-2 text-right text-xs text-faint">
                    {row.avg_latency_ms != null ? `${row.avg_latency_ms}ms` : "—"}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}
