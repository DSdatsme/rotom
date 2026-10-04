import Link from "next/link";
import type { JobHealth, RunStatus } from "@/lib/api";
import { RUN_STATUS } from "@/lib/view/run";
import { toneDot } from "@/lib/tone";
import { relativeTime } from "@/lib/format/datetime";
import { formatMs, formatUsd } from "@/lib/format/number";
import { normalizeTs } from "@/lib/obs-utils";

export function JobHealthTable({ jobs }: { jobs: JobHealth[] }) {
  if (jobs.length === 0) {
    return <p className="px-4 py-8 text-center text-sm text-muted-foreground">No runs recorded yet.</p>;
  }
  const now = Date.now();
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-border text-xs tracking-wider text-muted-foreground uppercase">
          <tr>
            <th className="px-4 py-2 font-medium">Job</th>
            <th className="px-4 py-2 font-medium">Last run</th>
            <th className="px-4 py-2 text-right font-medium">Runs</th>
            <th className="px-4 py-2 text-right font-medium">Success</th>
            <th className="px-4 py-2 text-right font-medium">p50 / p95</th>
            <th className="px-4 py-2 text-right font-medium">Avg cost</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/60">
          {jobs.map((j) => {
            const st = j.last_status ? RUN_STATUS[j.last_status as RunStatus] : null;
            const rate = j.runs ? Math.round((j.success / j.runs) * 100) : null;
            return (
              <tr key={j.kind} className="hover:bg-accent/40">
                <td className="px-4 py-2 font-medium">
                  <Link href={`/email/runs?kind=${encodeURIComponent(j.kind)}`} className="hover:underline">{j.kind}</Link>
                </td>
                <td className="px-4 py-2">
                  {j.last_run_id ? (
                    <Link href={`/email/runs/${j.last_run_id}`} className="inline-flex items-center gap-2 hover:underline">
                      {st && <span className={`inline-block size-2 rounded-full ${toneDot[st.tone]}`} />}
                      <span className="text-xs text-muted-foreground">
                        {relativeTime(j.last_started_at ? normalizeTs(j.last_started_at) : null, now)}
                      </span>
                    </Link>
                  ) : "—"}
                </td>
                <td className="mono px-4 py-2 text-right text-xs">{j.runs}</td>
                <td className={`mono px-4 py-2 text-right text-xs ${j.problems ? "text-warning" : ""}`}>
                  {rate == null ? "—" : `${rate}%`}
                </td>
                <td className="mono px-4 py-2 text-right text-xs">{formatMs(j.p50_ms)} / {formatMs(j.p95_ms)}</td>
                <td className="mono px-4 py-2 text-right text-xs">{formatUsd(j.avg_cost_usd)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
