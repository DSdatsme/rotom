import { getOverview } from "@/lib/api";
import { formatInt, formatMs, formatTokens, formatUsd } from "@/lib/format/number";
import { Panel } from "@/components/ui/panel";
import { EmptyState } from "@/components/ui/empty-state";
import { Kpi } from "@/components/obs/kpi";
import { WindowTabs } from "@/components/obs/window-tabs";
import { RunsChart } from "@/components/obs/runs-chart";
import { SpendChart } from "@/components/obs/spend-chart";
import { JobHealthTable } from "@/components/obs/job-health";
import { ProblemsList } from "@/components/obs/problems-list";

export const dynamic = "force-dynamic";

const WINDOWS: Record<string, { hours: number; label: string }> = {
  "24h": { hours: 24, label: "24h" },
  "7d": { hours: 24 * 7, label: "7d" },
  "30d": { hours: 24 * 30, label: "30d" },
};

export default async function ObservabilityOverview({
  searchParams,
}: {
  searchParams: Promise<{ window?: string }>;
}) {
  const { window = "24h" } = await searchParams;
  const win = WINDOWS[window] ?? WINDOWS["24h"];

  let data;
  try {
    data = await getOverview(win.hours);
  } catch (e) {
    return (
      <Panel>
        <EmptyState icon="TriangleAlert" title="Couldn't load observability data"
                    body={e instanceof Error ? e.message : "The backend API is unreachable."} />
      </Panel>
    );
  }
  // eslint-disable-next-line react-hooks/purity -- server component; request-time clock
  const now = Date.now();
  const k = data.kpis;
  const finished = k.runs - k.running;
  const successPct = finished ? Math.round((k.runs_ok / finished) * 100) : null;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Observability</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Runs, LLM spend and errors across rotom. Every row links to its trace.
          </p>
        </div>
        <WindowTabs param="window" value={window in WINDOWS ? window : "24h"} basePath="/observability"
                    options={Object.entries(WINDOWS).map(([value, w]) => ({ value, label: w.label }))} />
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <Kpi label="Runs" icon="History" value={formatInt(k.runs)}
             sub={successPct == null ? "none finished" : `${successPct}% succeeded`} />
        <Kpi label="Problems" icon="TriangleAlert" value={formatInt(k.problems)}
             sub="failed · degraded · interrupted" tone={k.problems ? "warning" : undefined} />
        <Kpi label="LLM spend" icon="CircleDollarSign" value={formatUsd(k.cost_usd)}
             sub={`${formatTokens(k.input_tokens)} in · ${formatTokens(k.output_tokens)} out`} />
        <Kpi label="LLM calls" icon="Sparkle" value={formatInt(k.llm_calls)}
             sub={`p95 ${formatMs(k.llm_p95_ms)}${k.llm_errors ? ` · ${k.llm_errors} failed` : ""}`}
             tone={k.llm_errors ? "warning" : undefined} />
        <Kpi label="Error logs" icon="ScrollText" value={formatInt(k.error_logs)}
             sub="ERROR + CRITICAL" tone={k.error_logs ? "danger" : undefined} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Runs over time" sub={`Per ${data.bucket}, by outcome`}>
          <RunsChart series={data.runs_series} bucket={data.bucket} />
        </Panel>
        <Panel title="LLM spend" sub={`Per ${data.bucket}, by model`}>
          <SpendChart points={data.cost_series} buckets={data.buckets} bucket={data.bucket} />
        </Panel>
      </div>

      <div className="grid gap-4 lg:grid-cols-[3fr_2fr]">
        <Panel title="Job health" sub="Per run kind, this window" noPad>
          <JobHealthTable jobs={data.jobs} now={now} />
        </Panel>
        <Panel title="Recent problems" sub="Failed runs and error logs" noPad>
          <ProblemsList problems={data.problems} now={now} />
        </Panel>
      </div>
    </div>
  );
}
