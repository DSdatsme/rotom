import Link from "next/link";
import { notFound } from "next/navigation";
import { getTrace, type RunStatus } from "@/lib/api";
import { RUN_STATUS } from "@/lib/view/run";
import { spanCategory, TRACE_TYPE_LABEL } from "@/lib/view/trace";
import { formatMs, formatTokens, formatUsd } from "@/lib/format/number";
import { formatDateTime } from "@/lib/obs-utils";
import { Panel } from "@/components/ui/panel";
import { EmptyState } from "@/components/ui/empty-state";
import { Kpi } from "@/components/obs/kpi";
import { TraceView } from "@/components/obs/trace-view";

export const dynamic = "force-dynamic";

export default async function TraceDetailPage({ params }: { params: Promise<{ traceId: string }> }) {
  const { traceId } = await params;
  let detail;
  try {
    detail = await getTrace(traceId);
  } catch (e) {
    if (e instanceof Error && /\bAPI 404\b/.test(e.message)) notFound();
    return (
      <Panel>
        <EmptyState icon="TriangleAlert" title="Couldn't load this trace" body={e instanceof Error ? e.message : undefined} />
      </Panel>
    );
  }
  if (detail.spans.length === 0) notFound();
  const ids = new Set(detail.spans.map((s) => s.span_id));
  const root = detail.spans.find((s) => !s.parent_span_id || !ids.has(s.parent_span_id)) ?? detail.spans[0];
  const llm = detail.spans.filter((s) => s.operation === "chat");
  const cost = llm.reduce((acc, s) => acc + (s.cost_usd ?? 0), 0);
  const tokens = llm.reduce((acc, s) => acc + (s.input_tokens ?? 0) + (s.output_tokens ?? 0), 0);
  const errors = detail.spans.filter((s) => s.status === "ERROR").length;
  const cat = spanCategory(root);
  const typeLabel = cat === "run" ? TRACE_TYPE_LABEL.run : cat === "agent" ? TRACE_TYPE_LABEL.chat : cat === "http" ? TRACE_TYPE_LABEL.http : TRACE_TYPE_LABEL.other;
  const runSt = detail.run ? RUN_STATUS[detail.run.status as RunStatus] : null;

  return (
    <div className="space-y-6">
      <div>
        <div className="text-xs text-muted-foreground">
          {typeLabel} trace · <span className="font-mono">{detail.trace_id}</span>
        </div>
        <h1 className="mt-1 font-mono text-xl font-semibold tracking-tight">{root.name}</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {formatDateTime(root.start_time)}
          {detail.run && (
            <>
              {" · "}
              <Link href={`/email/runs/${detail.run.id}`} className="text-brand hover:underline">
                run #{detail.run.id}
              </Link>
              {runSt && <> · {runSt.label}</>}
              {detail.run.summary && <> · {detail.run.summary}</>}
            </>
          )}
        </p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Kpi label="Duration" icon="Timer" value={formatMs(root.duration_ms)} sub={`${detail.spans.length} spans`} />
        <Kpi label="LLM calls" icon="Sparkle" value={String(llm.length)} sub={`${formatTokens(tokens)} tokens`} />
        <Kpi label="Cost" icon="CircleDollarSign" value={formatUsd(llm.length ? cost : null)} />
        <Kpi label="Errors" icon="TriangleAlert" value={String(errors)} tone={errors ? "danger" : undefined}
             sub={errors ? "see red spans" : "none"} />
      </div>
      <TraceView detail={detail} />
    </div>
  );
}
