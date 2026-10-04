import Link from "next/link";
import { getLlmStats, type LlmGroupStats } from "@/lib/api";
import { formatInt, formatMs, formatTokens, formatUsd } from "@/lib/format/number";
import { relativeTime } from "@/lib/format/datetime";
import { normalizeTs } from "@/lib/obs-utils";
import { Panel } from "@/components/ui/panel";
import { EmptyState } from "@/components/ui/empty-state";
import { Kpi } from "@/components/obs/kpi";
import { WindowTabs } from "@/components/obs/window-tabs";
import { SpendChart } from "@/components/obs/spend-chart";

export const dynamic = "force-dynamic";

const WINDOWS: Record<string, number> = { "1d": 1, "7d": 7, "30d": 30 };

function StatsTable({ rows, first }: { rows: (LlmGroupStats & { label: string; sub?: string | null })[]; first: string }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-border text-xs tracking-wider text-muted-foreground uppercase">
          <tr>
            <th className="px-4 py-2 font-medium">{first}</th>
            <th className="px-4 py-2 text-right font-medium">Calls</th>
            <th className="px-4 py-2 text-right font-medium">Errors</th>
            <th className="px-4 py-2 text-right font-medium">In</th>
            <th className="px-4 py-2 text-right font-medium">Out</th>
            <th className="px-4 py-2 text-right font-medium">Cached</th>
            <th className="px-4 py-2 text-right font-medium">p50 / p95</th>
            <th className="px-4 py-2 text-right font-medium">Cost</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/60">
          {rows.map((r) => (
            <tr key={r.label} className="hover:bg-accent/40">
              <td className="px-4 py-2">
                <div className="font-mono text-xs">{r.label}</div>
                {r.sub && <div className="text-[11px] text-faint">{r.sub}</div>}
              </td>
              <td className="mono px-4 py-2 text-right text-xs">{formatInt(r.calls)}</td>
              <td className={`mono px-4 py-2 text-right text-xs ${r.errors ? "text-destructive" : ""}`}>{r.errors || "—"}</td>
              <td className="mono px-4 py-2 text-right text-xs">{formatTokens(r.input_tokens)}</td>
              <td className="mono px-4 py-2 text-right text-xs">{formatTokens(r.output_tokens)}</td>
              <td className="mono px-4 py-2 text-right text-xs">{r.cache_read_tokens ? formatTokens(r.cache_read_tokens) : "—"}</td>
              <td className="mono px-4 py-2 text-right text-xs">{formatMs(r.p50_ms)} / {formatMs(r.p95_ms)}</td>
              <td className="mono px-4 py-2 text-right text-xs">{formatUsd(r.cost_usd)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default async function LlmPage({ searchParams }: { searchParams: Promise<{ window?: string }> }) {
  const { window = "7d" } = await searchParams;
  const windowKey = Object.hasOwn(WINDOWS, window) ? window : "7d";
  const days = WINDOWS[windowKey];
  let data;
  try {
    data = await getLlmStats(days);
  } catch (e) {
    return (
      <Panel>
        <EmptyState icon="TriangleAlert" title="Couldn't load LLM stats" body={e instanceof Error ? e.message : undefined} />
      </Panel>
    );
  }
  const k = data.kpis;
  // eslint-disable-next-line react-hooks/purity -- server component; request-time clock
  const now = Date.now();
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">LLM</h1>
          <p className="mt-1 text-sm text-muted-foreground">Every model call: spend, tokens, latency and failures.</p>
        </div>
        <WindowTabs param="window" value={windowKey} basePath="/observability/llm"
                    options={Object.keys(WINDOWS).map((w) => ({ value: w, label: w }))} />
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <Kpi label="Spend" icon="CircleDollarSign" value={formatUsd(k.cost_usd ?? 0)} sub={`${formatInt(k.calls)} calls`} />
        <Kpi label="Tokens" icon="Hash" value={formatTokens(k.input_tokens + k.output_tokens)}
             sub={`${formatTokens(k.input_tokens)} in · ${formatTokens(k.output_tokens)} out`} />
        <Kpi label="Cache hit" icon="DatabaseZap" value={k.cache_hit_pct == null ? "—" : `${k.cache_hit_pct}%`}
             sub="of input tokens" />
        <Kpi label="Latency" icon="Timer" value={formatMs(k.p95_ms)} sub={`p95 · p50 ${formatMs(k.p50_ms)}`} />
        <Kpi label="Failures" icon="TriangleAlert" value={formatInt(k.errors)}
             sub={k.calls ? `${((k.errors / k.calls) * 100).toFixed(1)}% of calls` : "—"}
             tone={k.errors ? "danger" : undefined} />
      </div>

      <Panel title="Daily spend" sub="Stacked by model">
        <SpendChart points={data.daily} buckets={data.buckets} bucket="day" />
      </Panel>

      <div className="grid gap-4 xl:grid-cols-2">
        <Panel title="By model" noPad>
          <StatsTable first="Model" rows={data.by_model.map((m) => ({ ...m, label: m.model, sub: m.provider }))} />
        </Panel>
        <Panel title="By role" sub="classify · draft · chat" noPad>
          <StatsTable first="Role" rows={data.by_role.map((r) => ({ ...r, label: r.role }))} />
        </Panel>
      </div>

      <Panel title="Recent calls" sub="Newest first — open one to see its prompt and response" noPad>
        {data.recent.length === 0 ? (
          <EmptyState icon="Sparkle" title="No LLM calls in this window" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-border text-xs tracking-wider text-muted-foreground uppercase">
                <tr>
                  <th className="px-4 py-2 font-medium">When</th>
                  <th className="px-4 py-2 font-medium">Role</th>
                  <th className="px-4 py-2 font-medium">Model</th>
                  <th className="px-4 py-2 font-medium">Run</th>
                  <th className="px-4 py-2 text-right font-medium">Latency</th>
                  <th className="px-4 py-2 text-right font-medium">Tokens</th>
                  <th className="px-4 py-2 text-right font-medium">Cost</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60">
                {data.recent.map((c) => (
                  <tr key={c.span_id} className="hover:bg-accent/40">
                    <td className="px-4 py-2 text-xs">
                      {c.trace_id ? (
                        <Link href={`/observability/traces/${c.trace_id}`} className="text-brand hover:underline">
                          {relativeTime(normalizeTs(c.start_time), now)}
                        </Link>
                      ) : (
                        <span className="text-muted-foreground">{relativeTime(normalizeTs(c.start_time), now)}</span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-xs">{c.role ?? "—"}</td>
                    <td className="px-4 py-2 font-mono text-xs">{c.model ?? "—"}</td>
                    <td className="px-4 py-2 text-xs text-muted-foreground">
                      {c.run_id ? <Link href={`/email/runs/${c.run_id}`} className="hover:underline">{c.run_kind} #{c.run_id}</Link> : "ad hoc"}
                    </td>
                    <td className={`mono px-4 py-2 text-right text-xs ${c.status === "ERROR" ? "text-destructive" : ""}`}>
                      {c.status === "ERROR" ? "failed" : formatMs(c.duration_ms)}
                    </td>
                    <td className="mono px-4 py-2 text-right text-xs">{formatTokens(c.input_tokens + c.output_tokens)}</td>
                    <td className="mono px-4 py-2 text-right text-xs">{formatUsd(c.cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
