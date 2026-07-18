// Logs Explorer — faceted search + live-tail. Exported to window.
const { useState: useStateL, useEffect: useEffectL, useRef: useRefL } = React;

const LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"];
const LVL_TOKEN = { DEBUG: "muted", INFO: "accent", WARNING: "warning", ERROR: "danger" };
const RANGES = [["15m", 8], ["1h", 22], ["24h", 46], ["7d", 70], ["All", 9999]];

function fmtNowTime() {
  const d = new Date(), p = (n) => String(n).padStart(2, "0");
  return p(d.getHours()) + ":" + p(d.getMinutes()) + ":" + p(d.getSeconds());
}

function LogRow({ l, fresh }) {
  return (
    <div className={"log-row lvl-" + LVL_TOKEN[l.lvl] + (fresh ? " fresh" : "")}>
      <span className={"log-lvl tone-" + LVL_TOKEN[l.lvl]}>{l.lvl}</span>
      <span className="log-kind">{l.kind}</span>
      <span className="log-run mono">{l.runId}</span>
      <span className="log-ts mono">{l.ts}</span>
      <span className="log-msg">{l.msg}</span>
    </div>
  );
}

function LogsExplorer({ loading }) {
  const { LOGS, LOG_TEMPLATES } = window.ROTOM;
  const [logs, setLogs] = useStateL(() => LOGS.map((l) => ({ ...l })));
  const [q, setQ] = useStateL("");
  const [levels, setLevels] = useStateL(() => new Set(LEVELS));
  const [kind, setKind] = useStateL("all");
  const [range, setRange] = useStateL("All");
  const [live, setLive] = useStateL(true);
  const [visible, setVisible] = useStateL(24);
  const liveSeq = useRefL(200000);

  const kinds = ["all", ...Array.from(new Set(LOGS.map((l) => l.kind)))];

  // live tail — prepend a new entry periodically
  useEffectL(() => {
    if (!live) return;
    const id = setInterval(() => {
      const tm = LOG_TEMPLATES[Math.floor(Math.random() * LOG_TEMPLATES.length)];
      const seq = ++liveSeq.current;
      setLogs((ls) => [{ id: "live" + seq, lvl: tm.lvl, kind: tm.kind, msg: tm.msg, ts: fmtNowTime(), runId: "r_" + (9100000 + seq).toString(36), seq, _fresh: true }, ...ls].slice(0, 240));
    }, 2600);
    return () => clearInterval(id);
  }, [live]);

  const rangeCap = RANGES.find((r) => r[0] === range)[1];
  const toggleLevel = (lv) => setLevels((s) => { const n = new Set(s); n.has(lv) ? n.delete(lv) : n.add(lv); return n; });

  const filtered = logs
    .filter((l) => levels.has(l.lvl))
    .filter((l) => kind === "all" || l.kind === kind)
    .filter((l) => !q.trim() || (l.msg + " " + l.kind + " " + l.runId).toLowerCase().includes(q.toLowerCase()))
    .slice(0, rangeCap);
  const shown = filtered.slice(0, visible);

  return (
    <div className="logs">
      <div className="logs-head">
        <h1 className="page-title">Logs Explorer</h1>
        <p className="page-sub">Structured application logs with faceted search and live-tail.</p>
      </div>

      <div className="logs-filter">
        <div className="lf-search">
          <Icon name="search" size={15} />
          <input className="lf-search-input" placeholder="Search messages, run ids, kinds…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <div className="level-chips">
          {LEVELS.map((lv) => (
            <button key={lv} className={"level-chip tone-" + LVL_TOKEN[lv] + (levels.has(lv) ? " on" : "")} onClick={() => toggleLevel(lv)}>
              <span className="lc-dot" />{lv}
            </button>
          ))}
        </div>
        <select className="kind-select" value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Filter by kind">
          {kinds.map((k) => <option key={k} value={k}>{k === "all" ? "All kinds" : k}</option>)}
        </select>
        <div className="range-seg">
          {RANGES.map(([r]) => (
            <button key={r} className={"range-btn" + (range === r ? " on" : "")} onClick={() => setRange(r)}>{r}</button>
          ))}
        </div>
        <button className={"live-toggle" + (live ? " on" : "")} onClick={() => setLive((v) => !v)}>
          <StatusDot tone={live ? "success" : "muted"} pulse={live} />
          {live ? "Live" : "Tail off"}
        </button>
      </div>

      <div className="logs-panel">
        {loading ? (
          <div className="logs-loading">
            {Array.from({ length: 12 }).map((_, i) => (
              <div className="log-row" key={i}><Skeleton w="48px" h={12} /><Skeleton w="64px" h={12} /><Skeleton w="72px" h={12} /><Skeleton w="60px" h={12} /><Skeleton w={i % 2 ? "70%" : "52%"} h={12} /></div>
            ))}
          </div>
        ) : shown.length === 0 ? (
          <EmptyState icon="scroll" title="No logs match these filters"
            body="Try clearing the search, enabling more levels, or widening the time range." />
        ) : (
          <React.Fragment>
            <div className="logs-rows">
              {shown.map((l) => <LogRow key={l.id} l={l} fresh={l._fresh} />)}
            </div>
            {filtered.length > visible && (
              <button className="load-older" onClick={() => setVisible((v) => v + 24)}>
                <Icon name="arrow-down" size={14} />Load older ({filtered.length - visible} more)
              </button>
            )}
          </React.Fragment>
        )}
      </div>
    </div>
  );
}

Object.assign(window, { LogsExplorer });
