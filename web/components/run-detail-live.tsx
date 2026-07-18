"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowUpRight, Activity } from "lucide-react";
import type { RunDetail, RunStatus } from "@/lib/api";
import type { Tone } from "@/lib/view/email";
import { formatTokens, computeDuration, parseJsonlLogs, formatDateTime } from "@/lib/obs-utils";
import { RUN_STATUS } from "@/lib/view/run";
import { toneDot } from "@/lib/tone";
import { Icon } from "@/components/ui/icon";
import { Panel } from "@/components/ui/panel";
import { LogsPanel } from "@/components/logs-panel";

const POLL_INTERVAL = 4000; // ms

/** Mock CSS tone tokens: our "brand" maps to the mock's "accent". */
function toneCls(tone: Tone): string {
  return tone === "brand" ? "accent" : tone;
}

export function RunDetailLive({ initialRun, runId }: { initialRun: RunDetail; runId: string }) {
  const [run, setRun] = useState<RunDetail>(initialRun);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [, setTick] = useState(0);

  const isRunning = run.status === "running";

  const refresh = async () => {
    try {
      const res = await fetch(`/api/run-proxy?id=${runId}`);
      if (res.ok) {
        const data: RunDetail = await res.json();
        setRun(data);
        if (data.status !== "running" && intervalRef.current) {
          clearInterval(intervalRef.current);
          intervalRef.current = null;
        }
      }
    } catch {
      // network blip — ignore
    }
  };

  useEffect(() => {
    if (isRunning) intervalRef.current = setInterval(refresh, POLL_INTERVAL);
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isRunning]);

  // tick every second so the live duration counts up
  useEffect(() => {
    if (!isRunning) return;
    const t = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, [isRunning]);

  const st = RUN_STATUS[run.status as RunStatus] ?? RUN_STATUS.failure;
  const tone = toneCls(st.tone);
  const durationStr = computeDuration(run.started_at, run.finished_at, run.status);
  const parsedLogs = parseJsonlLogs(run.logs);
  const totalIn = run.metrics.reduce((acc, m) => acc + m.input_tokens, 0);
  const totalOut = run.metrics.reduce((acc, m) => acc + m.output_tokens, 0);

  return (
    <div className="rundetail">
      <div className="rd-head">
        <Link href="/email/runs" className="rd-back" aria-label="Back to runs">
          <ArrowLeft size={15} />
        </Link>
        <div>
          {run.parent && (
            <div className="rd-parent mono">
              <Link href={`/email/runs/${run.parent.id}`} className="rd-parent-link">
                {run.parent.kind} #{run.parent.id}
              </Link>{" "}
              / {run.kind}
            </div>
          )}
          <h1 className="rd-title">
            {run.kind}
            <span className={"rd-status tone-" + tone}>
              <Icon name={st.icon} size={15} className={isRunning ? "animate-spin" : undefined} />
              {st.label}
            </span>
          </h1>
        </div>
      </div>

      <div className="rstat-grid">
        <div className="rstat">
          <span className="rstat-label">Status</span>
          <span className="rstat-value">
            <span className={"tone-text tone-" + tone}>
              <Icon name={st.icon} size={14} className={isRunning ? "animate-spin" : undefined} />
              {st.label}
            </span>
          </span>
        </div>
        <div className="rstat">
          <span className="rstat-label">Source</span>
          <span className="rstat-value mono">{run.source || "—"}</span>
        </div>
        <div className="rstat">
          <span className="rstat-label">Started</span>
          <span className="rstat-value mono">{formatDateTime(run.started_at) || "—"}</span>
        </div>
        <div className="rstat">
          <span className="rstat-label">Duration</span>
          <span className="rstat-value mono">{durationStr}</span>
        </div>
        <div className="rstat">
          <span className="rstat-label">In tokens</span>
          <span className="rstat-value mono">{formatTokens(totalIn)}</span>
        </div>
        <div className="rstat">
          <span className="rstat-label">Out tokens</span>
          <span className="rstat-value mono">{formatTokens(totalOut)}</span>
        </div>
        <div className="rstat full">
          <span className="rstat-label">Summary</span>
          <span className="rd-summary">{run.summary || (isRunning ? "In progress…" : "—")}</span>
        </div>
      </div>

      {run.error && (
        <div className="rd-error">
          <Icon name="CircleX" size={16} />
          <div>
            <div className="rd-error-title">Run {st.label.toLowerCase()}</div>
            <div className="rd-error-body mono">{run.error}</div>
          </div>
        </div>
      )}

      {run.metrics.length > 0 && (
        <Panel title="Model usage" noPad>
          <div className="overflow-x-auto">
            <table className="tbl" style={{ minWidth: "auto" }}>
              <thead>
                <tr>
                  <th>Model</th>
                  <th style={{ textAlign: "right" }}>In</th>
                  <th style={{ textAlign: "right" }}>Out</th>
                  <th style={{ textAlign: "right" }}>Avg latency</th>
                </tr>
              </thead>
              <tbody>
                {run.metrics.map((m, i) => (
                  <tr className="row" key={i}>
                    <td className="mono">{m.model}</td>
                    <td className="mono" style={{ textAlign: "right" }}>{formatTokens(m.input_tokens)}</td>
                    <td className="mono" style={{ textAlign: "right" }}>{formatTokens(m.output_tokens)}</td>
                    <td className="mono" style={{ textAlign: "right" }}>
                      {m.avg_latency_ms != null ? `${(m.avg_latency_ms / 1000).toFixed(2)}s` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}

      {run.external_url && (
        <a className="inngest-link" href={run.external_url} target="_blank" rel="noopener noreferrer">
          <Activity size={15} />
          <span>View steps in Inngest</span>
          <ArrowUpRight size={13} style={{ opacity: 0.7 }} />
        </a>
      )}

      {run.children && run.children.length > 0 && (
        <Panel title="Sub-runs" sub={`${run.children.length} child task${run.children.length > 1 ? "s" : ""}`}>
          <div className="subrun-tree">
            {run.children.map((c) => {
              const cst = RUN_STATUS[c.status as RunStatus] ?? RUN_STATUS.failure;
              return (
                <Link key={c.id} href={`/email/runs/${c.id}`} className="subrun">
                  <span className={`subrun-dot ${toneDot[cst.tone]}`} />
                  <span className="subrun-kind">{c.kind}</span>
                  <span className="subrun-src mono">{c.source}</span>
                  <span className="subrun-id mono">#{c.id}</span>
                </Link>
              );
            })}
          </div>
        </Panel>
      )}

      <LogsPanel
        logs={parsedLogs}
        isLive={isRunning}
        title="Execution logs"
        showLogger={false}
        showRunId={false}
        className="max-h-[360px]"
      />
    </div>
  );
}
