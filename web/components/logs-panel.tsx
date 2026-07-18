"use client";

/**
 * LogsPanel — reusable GitHub-Actions-style structured log viewer.
 *
 * Used by:
 *   - RunDetailLive (displays JSONL logs captured by a run)
 *   - LogsExplorer (displays LogEntry rows from the DB explorer)
 *
 * Accepts either ParsedLog[] (from parseJsonlLogs) or LogEntry-shaped rows
 * (both have ts/level/logger/msg/exc_info/run_id).
 */

import { useState } from "react";
import { formatDateTimeSeconds, levelColor, levelBg } from "@/lib/obs-utils";

export interface LogRow {
  ts?: string | null;
  level?: string | null;
  logger?: string | null;
  msg?: string | null;
  exc_info?: string | null;
  run_id?: string | number | null;
  kind?: string | null;
  extra?: string | null;
}

interface LogsRowProps {
  log: LogRow;
  showLogger?: boolean;
  showRunId?: boolean;
}

function LogsRow({ log, showLogger = true, showRunId = false }: LogsRowProps) {
  const [expanded, setExpanded] = useState(false);

  let extra: Record<string, unknown> = {};
  if (log.extra) {
    try {
      extra = JSON.parse(log.extra);
    } catch {
      /* ignore */
    }
  }
  const knownKeys = new Set(["ts", "level", "logger", "msg", "exc_info", "run_id", "kind", "extra"]);
  const inlineExtra: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(log)) {
    if (!knownKeys.has(k) && v !== undefined) inlineExtra[k] = v;
  }
  const mergedExtra = { ...extra, ...inlineExtra };

  const excInfo = log.exc_info ?? (mergedExtra.exc_info as string | undefined);
  delete mergedExtra.exc_info;
  const hasExtra = Object.keys(mergedExtra).length > 0 || !!excInfo;

  const level = log.level || "INFO";
  const time = formatDateTimeSeconds(log.ts ?? null);

  return (
    <div
      className={`px-3 py-1 hover:bg-accent/50 transition-colors cursor-pointer ${levelBg(level)}`}
      onClick={() => setExpanded((v) => !v)}
    >
      <div className="flex gap-3 items-start">
        <div className="text-faint w-36 shrink-0 text-xs select-none font-mono mt-0.5">{time}</div>
        <div className={`w-14 shrink-0 text-xs font-semibold select-none font-mono mt-0.5 ${levelColor(level)}`}>
          {level}
        </div>
        {showLogger && (
          <div className="text-muted-foreground w-32 shrink-0 text-xs select-none font-mono truncate mt-0.5 hidden md:block">
            {log.logger || ""}
          </div>
        )}
        <div
          className={`text-fg-2 flex-1 min-w-0 text-[13px] leading-relaxed font-mono ${
            expanded ? "whitespace-pre-wrap break-words" : "truncate"
          }`}
        >
          {log.msg || ""}
          {hasExtra && !expanded && <span className="ml-2 text-faint text-xs">[…]</span>}
        </div>
        {showRunId && (log.kind || log.run_id != null) && (
          <div className="shrink-0 hidden md:flex items-center gap-1.5 mt-0.5">
            {log.kind && (
              <span className="text-[11px] font-mono px-1.5 py-0.5 rounded bg-brand-soft text-brand truncate max-w-[150px]">
                {log.kind}
              </span>
            )}
            {log.run_id != null && <span className="text-xs text-faint font-mono">#{log.run_id}</span>}
          </div>
        )}
      </div>

      {expanded && (
        <div
          className={`mt-2 space-y-2 ${
            showLogger ? "ml-[calc(9rem+3.5rem+8rem+0.75rem)]" : "ml-[calc(9rem+3.5rem+0.75rem)]"
          }`}
        >
          {excInfo && (
            <div className="text-destructive text-xs border-l-2 border-destructive/30 pl-3 py-1 bg-destructive/8 rounded-r font-mono whitespace-pre-wrap">
              {String(excInfo)}
            </div>
          )}
          {Object.keys(mergedExtra).length > 0 && (
            <pre className="text-xs text-muted-foreground bg-card-3 rounded p-2 overflow-x-auto">
              {JSON.stringify(mergedExtra, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

interface LogsPanelProps {
  logs: LogRow[];
  isLive?: boolean;
  loading?: boolean;
  title?: string;
  showLogger?: boolean;
  showRunId?: boolean;
  /** Slot rendered after the last row (e.g. "load more" button) */
  footer?: React.ReactNode;
  className?: string;
}

export function LogsPanel({
  logs,
  isLive = false,
  loading = false,
  title = "Logs",
  showLogger = true,
  showRunId = false,
  footer,
  className = "",
}: LogsPanelProps) {
  return (
    <div className={`bg-background rounded-lg shadow-sm border border-border overflow-hidden font-mono text-sm flex flex-col ${className}`}>
      {/* Header */}
      <div className="shrink-0 bg-card border-b border-border p-3 px-4 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-fg-2">{title}</h3>
        <div className="flex items-center gap-2">
          {loading && <span className="text-xs text-muted-foreground animate-pulse">loading…</span>}
          {isLive && (
            <span className="text-xs text-brand flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-brand animate-pulse" />
              live
            </span>
          )}
          <span className="text-xs text-muted-foreground bg-card-3 px-2 py-1 rounded-full">{logs.length} lines</span>
        </div>
      </div>

      {/* Column headers */}
      <div className="shrink-0 flex gap-3 px-3 py-1.5 border-b border-border bg-card/50">
        <div className="w-36 shrink-0 text-[10px] font-semibold text-faint uppercase tracking-wider">Time</div>
        <div className="w-14 shrink-0 text-[10px] font-semibold text-faint uppercase tracking-wider">Level</div>
        {showLogger && (
          <div className="w-32 shrink-0 text-[10px] font-semibold text-faint uppercase tracking-wider hidden md:block">
            Logger
          </div>
        )}
        <div className="flex-1 text-[10px] font-semibold text-faint uppercase tracking-wider">Message</div>
        {showRunId && (
          <div className="hidden md:block text-[10px] font-semibold text-faint uppercase tracking-wider">Context</div>
        )}
      </div>

      {/* Rows */}
      <div className="flex-1 min-h-0 divide-y divide-border/60 overflow-y-auto overflow-x-auto">
        {logs.length === 0 && !loading ? (
          <div className="text-muted-foreground text-sm italic py-8 text-center">
            {isLive ? "Waiting for logs…" : "No logs captured."}
          </div>
        ) : (
          logs.map((log, i) => (
            <LogsRow
              key={(log as { id?: number }).id ?? i}
              log={log}
              showLogger={showLogger}
              showRunId={showRunId}
            />
          ))
        )}
      </div>

      {footer && <div className="shrink-0 p-3 text-center border-t border-border">{footer}</div>}
    </div>
  );
}
