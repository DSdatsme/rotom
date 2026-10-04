import Link from "next/link";
import type { Problem, RunStatus } from "@/lib/api";
import { RUN_STATUS } from "@/lib/view/run";
import { toneDot } from "@/lib/tone";
import { relativeTime } from "@/lib/format/datetime";
import { normalizeTs } from "@/lib/obs-utils";

export function ProblemsList({ problems, now }: { problems: Problem[]; now: number }) {
  if (problems.length === 0) {
    return <p className="px-4 py-8 text-center text-sm text-muted-foreground">Nothing failed in this window.</p>;
  }
  return (
    <ul className="divide-y divide-border/60">
      {problems.map((p) => {
        const href = p.trace_id
          ? `/observability/traces/${p.trace_id}`
          : p.run_id != null ? `/email/runs/${p.run_id}` : "/observability/logs";
        const dot = p.type === "run" ? toneDot[RUN_STATUS[p.status as RunStatus]?.tone ?? "danger"] : toneDot.danger;
        return (
          <li key={p.type === "run" ? `r${p.run_id}` : `l${p.id}`}>
            <Link href={href} className="flex items-start gap-3 px-4 py-2.5 hover:bg-accent/40">
              <span className={`mt-1.5 inline-block size-2 shrink-0 rounded-full ${dot}`} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 text-sm">
                  <span className="font-medium">{p.type === "run" ? p.kind : p.logger}</span>
                  <span className="text-xs text-faint">{relativeTime(normalizeTs(p.ts), now)}</span>
                </div>
                <div className="truncate text-xs text-muted-foreground">
                  {p.type === "run" ? p.error || p.summary || p.status : p.msg}
                </div>
              </div>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
