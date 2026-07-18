import type { RunLog, RunDetail, RunStatus } from "@/lib/api";
import type { Tone } from "@/lib/view/email";
import { relativeTime, formatDuration } from "@/lib/format/datetime";

export const RUN_STATUS: Record<RunStatus, { tone: Tone; label: string; icon: string }> = {
  success: { tone: "success", label: "Success", icon: "CircleCheck" },
  running: { tone: "brand", label: "Running", icon: "Loader" },
  degraded: { tone: "warning", label: "Degraded", icon: "TriangleAlert" },
  interrupted: { tone: "warning", label: "Interrupted", icon: "TriangleAlert" },
  failure: { tone: "danger", label: "Failed", icon: "CircleX" },
};

export function runDurationMs(
  r: Pick<RunLog, "started_at" | "finished_at">,
  now: number = Date.now(),
): number | null {
  if (!r.started_at) return null;
  const end = r.finished_at ? Date.parse(r.finished_at) : now;
  return end - Date.parse(r.started_at);
}

export function runTokenTotals(metrics: RunDetail["metrics"]): { input: number; output: number } {
  return metrics.reduce(
    (acc, m) => ({ input: acc.input + m.input_tokens, output: acc.output + m.output_tokens }),
    { input: 0, output: 0 },
  );
}

export interface RunView {
  id: number;
  kind: string;
  source: string;
  summary: string;
  status: { tone: Tone; label: string; icon: string };
  isLive: boolean;
  started: string;
  durationLabel: string;
  parentRunId: number | null;
}

export function toRunView(r: RunLog, now: number = Date.now()): RunView {
  return {
    id: r.id,
    kind: r.kind,
    source: r.source,
    summary: r.summary,
    status: RUN_STATUS[r.status],
    isLive: r.status === "running",
    started: relativeTime(r.started_at, now),
    durationLabel: formatDuration(runDurationMs(r, now)),
    parentRunId: r.parent_run_id,
  };
}
