"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { LogEntry, LogsPage } from "@/lib/api";
import { LogsPanel } from "@/components/logs-panel";

const POLL_INTERVAL = 3000; // ms for live-tail
const PAGE_SIZE = 100;

// ---- time range helpers -----------------------------------------------------

const TIME_RANGES = [
  { label: "15m", minutes: 15 },
  { label: "1h", minutes: 60 },
  { label: "24h", minutes: 60 * 24 },
  { label: "7d", minutes: 60 * 24 * 7 },
  { label: "All", minutes: 0 },
];

function sinceFromRange(minutes: number): string | undefined {
  if (!minutes) return undefined;
  const d = new Date(Date.now() - minutes * 60 * 1000);
  return d.toISOString();
}

// ---- build query string for proxy endpoint ----------------------------------

function buildQs(opts: {
  level: string;
  kind: string;
  q: string;
  since?: string;
  before_id?: number;
}): string {
  const p = new URLSearchParams();
  if (opts.level) p.set("level", opts.level);
  if (opts.kind) p.set("kind", opts.kind);
  if (opts.q) p.set("q", opts.q);
  if (opts.since) p.set("since", opts.since);
  if (opts.before_id != null) p.set("before_id", String(opts.before_id));
  p.set("limit", String(PAGE_SIZE));
  return p.toString();
}

// Run kinds known to the backend (callers of record_run). Dynamic/extra kinds
// seen in the loaded rows are merged in at render time.
const KNOWN_KINDS = ["gmail_triage", "draft_generation", "reminder_fire", "code_review", "coder"];

// ---- Level chip multi-select ------------------------------------------------

const ALL_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"];

function LevelChips({
  selected,
  onChange,
}: {
  selected: string[];
  onChange: (levels: string[]) => void;
}) {
  const toggle = (l: string) =>
    selected.includes(l)
      ? onChange(selected.filter((x) => x !== l))
      : onChange([...selected, l]);

  return (
    <div className="flex gap-1.5 flex-wrap">
      {ALL_LEVELS.map((l) => {
        const active = selected.includes(l);
        const color =
          l === "ERROR"
            ? active
              ? "bg-destructive/20 text-destructive border-destructive/50"
              : "text-destructive/60 border-destructive/20"
            : l === "WARNING"
            ? active
              ? "bg-warning/20 text-warning border-warning/50"
              : "text-warning/60 border-warning/20"
            : l === "DEBUG"
            ? active
              ? "bg-card-3 text-fg-2 border-border"
              : "text-faint border-border"
            : active
            ? "bg-brand-soft text-brand border-brand-line"
            : "text-brand/60 border-brand/20";
        return (
          <button
            key={l}
            onClick={() => toggle(l)}
            className={`text-xs font-mono font-semibold px-2.5 py-0.5 rounded-full border transition-colors ${color}`}
          >
            {l}
          </button>
        );
      })}
    </div>
  );
}

// ---- Main component ---------------------------------------------------------

interface LogsExplorerProps {
  initialPage: LogsPage;
}

export function LogsExplorer({ initialPage }: LogsExplorerProps) {
  // Filter state
  const [levels, setLevels] = useState<string[]>([]);
  const [kind, setKind] = useState("");
  const [q, setQ] = useState("");
  const [rangeIdx, setRangeIdx] = useState(1); // default "1h"
  const [liveTail, setLiveTail] = useState(false);

  // Logs state
  const [logs, setLogs] = useState<LogEntry[]>(initialPage.logs);
  const [nextBeforeId, setNextBeforeId] = useState<number | null>(
    initialPage.next_before_id,
  );
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // Track latest id for live-tail — needed to prepend newer rows
  const latestIdRef = useRef<number | null>(logs[0]?.id ?? null);

  const range = TIME_RANGES[rangeIdx];

  // Known kinds + any extra kinds present in the loaded rows.
  const kindOptions = useMemo(() => {
    const set = new Set<string>(KNOWN_KINDS);
    logs.forEach((l) => l.kind && set.add(l.kind));
    return Array.from(set).sort();
  }, [logs]);

  // Build filter deps string for effect comparison
  const filtersKey = `${levels.join(",")}|${kind}|${q}|${rangeIdx}`;

  // ---- fetch helpers --------------------------------------------------------

  const fetchPage = useCallback(
    async (before_id?: number): Promise<LogsPage | null> => {
      const since = sinceFromRange(range.minutes);
      const qs = buildQs({ level: levels.join(","), kind, q, since, before_id });
      try {
        const res = await fetch(`/api/logs-proxy?${qs}`);
        if (!res.ok) return null;
        return await res.json();
      } catch {
        return null;
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [filtersKey],
  );

  // Reload from scratch (filter changed or live-tail initial)
  const reload = useCallback(async () => {
    setLoading(true);
    const page = await fetchPage();
    setLoading(false);
    if (!page) return;
    setLogs(page.logs);
    setNextBeforeId(page.next_before_id);
    latestIdRef.current = page.logs[0]?.id ?? null;
  }, [fetchPage]);

  // Load older records (scroll-down / "load more")
  const loadMore = useCallback(async () => {
    if (!nextBeforeId || loadingMore) return;
    setLoadingMore(true);
    const page = await fetchPage(nextBeforeId);
    setLoadingMore(false);
    if (!page) return;
    setLogs((prev) => {
      const ids = new Set(prev.map((r) => r.id));
      return [...prev, ...page.logs.filter((r) => !ids.has(r.id))];
    });
    setNextBeforeId(page.next_before_id);
  }, [fetchPage, nextBeforeId, loadingMore]);

  // Poll for newer records (live-tail)
  const pollNewer = useCallback(async () => {
    const since = sinceFromRange(range.minutes);
    const qs = buildQs({ level: levels.join(","), kind, q, since });
    try {
      const res = await fetch(`/api/logs-proxy?${qs}`);
      if (!res.ok) return;
      const page: LogsPage = await res.json();
      const currentTop = latestIdRef.current;
      const newer = currentTop
        ? page.logs.filter((r) => r.id > currentTop)
        : page.logs;
      if (newer.length > 0) {
        setLogs((prev) => {
          const ids = new Set(prev.map((r) => r.id));
          const fresh = newer.filter((r) => !ids.has(r.id));
          return [...fresh, ...prev];
        });
        latestIdRef.current = newer[0].id;
      }
    } catch {
      /* ignore */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtersKey]);

  // ---- effects --------------------------------------------------------------

  // Reload when filters change
  useEffect(() => {
    reload();
  }, [reload]);

  // Live-tail polling
  useEffect(() => {
    if (!liveTail) {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
      return;
    }
    pollRef.current = setInterval(pollNewer, POLL_INTERVAL);
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [liveTail, pollNewer]);

  // ---- render ---------------------------------------------------------------

  const loadMoreButton = nextBeforeId != null ? (
    <button
      onClick={loadMore}
      disabled={loadingMore}
      className="text-xs text-muted-foreground hover:text-foreground transition-colors disabled:opacity-50"
    >
      {loadingMore ? "Loading…" : "Load older logs"}
    </button>
  ) : null;

  return (
    <div className="space-y-4">
      {/* Filter bar */}
      <div className="flex flex-wrap gap-3 items-center p-4 bg-card border border-border rounded-xl">
        {/* Text search */}
        <input
          type="text"
          placeholder="Search messages…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          className="flex-1 min-w-[180px] bg-card-3 border border-border rounded-lg px-3 py-1.5 text-sm text-fg-2 placeholder:text-faint focus:outline-none focus:border-brand-line font-mono"
        />

        {/* Level chips */}
        <LevelChips selected={levels} onChange={setLevels} />

        {/* Kind filter */}
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value)}
          aria-label="Filter by run kind"
          className="bg-card-3 border border-border rounded-lg px-3 py-1.5 text-sm text-fg-2 focus:outline-none focus:border-brand-line font-mono [color-scheme:dark]"
        >
          <option value="">All kinds</option>
          {kindOptions.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>

        {/* Time range */}
        <div className="flex gap-1 bg-card-3 rounded-lg p-0.5">
          {TIME_RANGES.map((r, i) => (
            <button
              key={r.label}
              onClick={() => setRangeIdx(i)}
              className={`text-xs px-2.5 py-1 rounded-md font-mono transition-colors ${
                rangeIdx === i
                  ? "bg-accent text-foreground"
                  : "text-faint hover:text-fg-2"
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>

        {/* Live-tail toggle */}
        <button
          onClick={() => setLiveTail((v) => !v)}
          className={`flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border transition-colors font-mono ${
            liveTail
              ? "bg-brand-soft border-brand-line text-brand"
              : "border-border text-faint hover:text-fg-2"
          }`}
        >
          {liveTail && (
            <span className="w-1.5 h-1.5 rounded-full bg-brand animate-ping" />
          )}
          {liveTail ? "Live" : "Tail off"}
        </button>
      </div>

      {/* Reuses the shared LogsPanel — passes LogEntry rows directly */}
      <LogsPanel
        logs={logs}
        isLive={liveTail}
        loading={loading}
        title="Application Logs"
        showLogger={true}
        showRunId={true}
        footer={loadMoreButton}
        className="max-h-[calc(100vh-260px)] overflow-hidden"
      />
    </div>
  );
}
