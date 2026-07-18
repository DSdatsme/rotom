"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { X } from "lucide-react";
import type { RunLog } from "@/lib/api";
import type { Tone } from "@/lib/view/email";
import { RUN_STATUS } from "@/lib/view/run";
import { relativeTime, formatDuration } from "@/lib/format/datetime";
import { Icon } from "@/components/ui/icon";
import { Panel } from "@/components/ui/panel";
import { EmptyState } from "@/components/ui/empty-state";
import { TriggerRunButton } from "@/components/trigger-run-button";

const POLL_INTERVAL = 4000; // ms

/** Mock CSS tone tokens: our "brand" maps to the mock's "accent". */
function toneCls(tone: Tone): string {
  return tone === "brand" ? "accent" : tone;
}

export function RunsList({ initialRuns }: { initialRuns: RunLog[] }) {
  const [runs, setRuns] = useState<RunLog[]>(initialRuns);
  const [source, setSource] = useState<string>("");
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const router = useRouter();

  const hasRunning = runs.some((r) => r.status === "running");

  const sources = useMemo(() => {
    const seen = new Set<string>(["scheduler", "manual", "chat", "inngest"]);
    initialRuns.forEach((r) => r.source && seen.add(r.source));
    return Array.from(seen);
  }, [initialRuns]);

  const refresh = async () => {
    try {
      const qs = new URLSearchParams({ limit: "50" });
      if (source) qs.set("source", source);
      const res = await fetch(`/api/runs-proxy?${qs.toString()}`);
      if (res.ok) setRuns(await res.json());
    } catch {
      // silently swallow — network blip
    }
  };

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source]);

  useEffect(() => {
    if (hasRunning) {
      intervalRef.current = setInterval(refresh, POLL_INTERVAL);
    } else if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasRunning, source]);

  const now = Date.now();

  return (
    <div className="runs">
      <div className="runs-head">
        <div>
          <h1 className="page-title">Recent runs</h1>
          <p className="page-sub">
            Background tasks and triage logs.
            {hasRunning && (
              <span className="runs-livenote">
                <span className="run-live-dot" />
                polling live
              </span>
            )}
          </p>
        </div>
        <TriggerRunButton />
      </div>

      <div className="src-facets">
        <button className={"src-pill" + (source === "" ? " active" : "")} onClick={() => setSource("")}>
          All sources
        </button>
        {sources.map((s) => (
          <button key={s} className={"src-pill" + (source === s ? " active" : "")} onClick={() => setSource(s)}>
            {s}
            {source === s && (
              <span className="src-pill-x" onClick={(e) => { e.stopPropagation(); setSource(""); }}>
                <X size={11} />
              </span>
            )}
          </button>
        ))}
      </div>

      {runs.length === 0 ? (
        <Panel>
          <EmptyState
            icon="History"
            title={source ? "No runs from this source" : "No runs recorded yet"}
            body={
              source
                ? "Nothing matches this source filter yet."
                : "Background tasks and triage runs will appear here as they execute."
            }
          />
        </Panel>
      ) : (
        <div className="run-list">
          {runs.map((run) => {
            const st = RUN_STATUS[run.status];
            const tone = toneCls(st.tone);
            const live = run.status === "running";
            const durMs = run.started_at
              ? (run.finished_at ? Date.parse(run.finished_at) : now) - Date.parse(run.started_at)
              : null;
            return (
              <button key={run.id} className="run-row" onClick={() => router.push(`/email/runs/${run.id}`)}>
                <span className={`run-spine tone-${tone}${live ? " live" : ""}`} />
                <span className={`run-stat-ic tone-${tone}`}>
                  <Icon name={st.icon} size={16} className={live ? "animate-spin" : undefined} />
                </span>
                <span className="run-main">
                  <span className="run-top">
                    <span className="run-kind">{run.kind}</span>
                    <span className="run-src mono">{run.source}</span>
                    {run.parent_run_id != null && <span className="run-parent mono">↳ #{run.parent_run_id}</span>}
                    {live && (
                      <span className="run-live">
                        <span className="run-live-dot" />
                        LIVE
                      </span>
                    )}
                  </span>
                  <span className="run-summary">
                    {run.summary ||
                      (live ? "In progress…" : st.label)}
                  </span>
                </span>
                <span className="run-meta">
                  <span className={`run-stat-label tone-${tone}`}>{st.label}</span>
                  <span className="run-time mono">
                    {live
                      ? `running ${durMs != null ? Math.floor(durMs / 1000) : 0}s`
                      : run.started_at
                        ? relativeTime(run.started_at, now)
                        : formatDuration(durMs)}
                  </span>
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
