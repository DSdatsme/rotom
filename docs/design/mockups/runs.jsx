// Runs list + Run detail (trace inspector). Exported to window.
const { useState: useStateRn, useEffect: useEffectRn, useRef: useRefRn } = React;

const RUN_STATUS = {
  success: { token: "success", icon: "circle-check", label: "Success" },
  running: { token: "accent", icon: "loader", label: "Running" },
  interrupted: { token: "warning", icon: "alert-triangle", label: "Interrupted" },
  failed: { token: "danger", icon: "x-circle", label: "Failed" },
};
const SOURCES = ["all", "scheduler", "manual", "chat", "inngest"];

function relTime(sec) {
  if (sec < 60) return sec + "s ago";
  if (sec < 3600) return Math.floor(sec / 60) + "m ago";
  if (sec < 86400) return Math.floor(sec / 3600) + "h ago";
  return Math.floor(sec / 86400) + "d ago";
}
function fmtDur(ms) {
  if (ms == null) return "—";
  if (ms < 1000) return ms + "ms";
  const s = ms / 1000;
  if (s < 60) return s.toFixed(2) + "s";
  return Math.floor(s / 60) + "m " + Math.round(s % 60) + "s";
}
function fmtTok(n) { if (n >= 1e6) return (n / 1e6).toFixed(2) + "M"; if (n >= 1e3) return (n / 1e3).toFixed(1) + "K"; return "" + n; }
function fmtInt(n) { return n.toLocaleString("en-US"); }
function offClock(off) {
  const d = new Date(Date.now() - off * 1000), p = (n) => String(n).padStart(2, "0");
  return p(d.getHours()) + ":" + p(d.getMinutes()) + ":" + p(d.getSeconds());
}

/* ============================================================ RUNS LIST */
function RunRow({ r, now, onOpen }) {
  const st = RUN_STATUS[r.status];
  const live = r.status === "running";
  const liveSec = Math.floor((now - r._start) / 1000);
  return (
    <button className="run-row" onClick={() => onOpen(r.id)}>
      <span className={"run-spine tone-" + st.token + (live ? " live" : "")} />
      <span className={"run-stat-ic tone-" + st.token}><Icon name={st.icon} size={16} /></span>
      <span className="run-main">
        <span className="run-top">
          <span className="run-kind">{r.kind}</span>
          <span className="run-src mono">{r.source}</span>
          {r.parent && <span className="run-parent mono">↳ #{r.parent}</span>}
          {live && <span className="run-live"><span className="run-live-dot" />live</span>}
        </span>
        <span className="run-summary">{r.summary}</span>
      </span>
      <span className="run-meta">
        <span className={"run-stat-label tone-" + st.token}>{st.label}</span>
        <span className="run-time mono">{live ? "running " + liveSec + "s" : relTime(r.relSec)}</span>
      </span>
    </button>
  );
}

function RunRowSkeleton() {
  return (
    <div className="run-row skel">
      <span className="run-spine tone-muted" />
      <Skeleton w={28} h={28} r={8} />
      <span className="run-main" style={{ gap: 7 }}>
        <Skeleton w="40%" h={13} /><Skeleton w="65%" h={11} />
      </span>
      <Skeleton w="60px" h={11} />
    </div>
  );
}

function RunsList({ runs, loading, now, onOpen, onTrigger }) {
  const [src, setSrc] = useStateRn("all");
  const rows = src === "all" ? runs : runs.filter((r) => r.source === src || (r.subs || []).some((s) => s.source === src));
  const anyRunning = runs.some((r) => r.status === "running");

  return (
    <div className="runs">
      <div className="runs-head">
        <div>
          <h1 className="page-title">Recent runs</h1>
          <p className="page-sub">Background tasks and triage logs.{anyRunning && <span className="runs-livenote"><span className="run-live-dot" />polling live</span>}</p>
        </div>
        <Button variant="primary" size="md" icon="zap" onClick={onTrigger}>Trigger run</Button>
      </div>

      <div className="src-facets">
        {SOURCES.map((s) => (
          <button key={s} className={"src-pill" + (src === s ? " active" : "")} onClick={() => setSrc(s)}>
            {s === "all" ? "All sources" : s}
            {src === s && s !== "all" && <span className="src-pill-x"><Icon name="x" size={11} /></span>}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="run-list">{[0, 1, 2, 3, 4].map((i) => <RunRowSkeleton key={i} />)}</div>
      ) : rows.length === 0 ? (
        <Panel>
          <EmptyState icon="history" title={runs.length === 0 ? "No runs recorded yet" : "No runs from this source"}
            body={runs.length === 0 ? "Background tasks and triage runs will appear here as they execute." : "Nothing matches this source filter yet."}
            action={runs.length === 0 ? <Button size="sm" icon="zap" onClick={onTrigger}>Trigger a run</Button> : <Button size="sm" onClick={() => setSrc("all")}>Show all</Button>} />
        </Panel>
      ) : (
        <div className="run-list">
          {rows.map((r) => <RunRow key={r.id} r={r} now={now} onOpen={onOpen} />)}
        </div>
      )}
    </div>
  );
}

/* ============================================================ RUN DETAIL */
function RunStat({ label, children, live, full }) {
  return (
    <div className={"rstat" + (full ? " full" : "")}>
      <span className="rstat-label">{label}{live && <span className="run-live-dot" />}</span>
      <span className="rstat-value">{children}</span>
    </div>
  );
}

function RunDetail({ run, runs, now, onOpenRun, onBackList }) {
  if (!run) return null;
  const st = RUN_STATUS[run.status];
  const live = run.status === "running";
  const parent = run.parent ? runs.find((r) => r.id === run.parent) : null;
  const liveDur = live ? now - run._start : run.durMs;
  const totalIn = run.tokIn, totalOut = run.tokOut;

  return (
    <div className="rundetail">
      <div className="rd-head">
        <button className="rd-back" onClick={onBackList}><Icon name="arrow-left" size={15} /></button>
        <div className="rd-title-wrap">
          {parent && <div className="rd-parent mono"><button className="rd-parent-link" onClick={() => onOpenRun(parent.id)}>{parent.kind} #{parent.id}</button> / {run.kind}</div>}
          <h1 className="rd-title">{run.kind}
            <span className={"rd-status tone-" + st.token}><Icon name={st.icon} size={15} />{st.label}{live && <span className="run-live-dot" />}</span>
          </h1>
        </div>
      </div>

      <div className="rstat-grid">
        <RunStat label="Status"><span className={"tone-text tone-" + st.token}><Icon name={st.icon} size={14} />{st.label}</span></RunStat>
        <RunStat label="Source"><span className="mono">{run.source}</span></RunStat>
        <RunStat label="Started"><span className="mono">{relTime(run.relSec)}</span></RunStat>
        <RunStat label="Duration" live={live}><span className="mono">{fmtDur(liveDur)}</span></RunStat>
        <RunStat label="In tokens"><span className="mono">{fmtInt(totalIn)}</span></RunStat>
        <RunStat label="Out tokens"><span className="mono">{fmtInt(totalOut)}</span></RunStat>
        <RunStat label="Summary" full><span className="rd-summary">{run.summary}</span></RunStat>
      </div>

      {run.status === "failed" && run.error && (
        <div className="rd-error">
          <Icon name="x-circle" size={16} />
          <div><div className="rd-error-title">Run failed</div><div className="rd-error-body mono">{run.error}</div></div>
        </div>
      )}

      <Panel title="Model usage" noPad>
        <div className="usage-tbl-wrap">
          <table className="tbl usage-tbl">
            <colgroup><col /><col style={{ width: "120px" }} /><col style={{ width: "120px" }} /><col style={{ width: "130px" }} /></colgroup>
            <thead><tr><th>Model</th><th className="num">In</th><th className="num">Out</th><th className="num">Avg latency</th></tr></thead>
            <tbody>
              {run.models.map((m, i) => (
                <tr className="row" key={i}>
                  <td className="mono col-model">{m.model}</td>
                  <td className="num mono">{fmtInt(m.in)}</td>
                  <td className="num mono">{fmtInt(m.out)}</td>
                  <td className="num mono">{(m.lat / 1000).toFixed(2)}s</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <a className="inngest-link" href="#" onClick={(e) => e.preventDefault()}>
        <Icon name="activity" size={15} />
        <span>View steps in Inngest</span>
        <Icon name="arrow-up" size={13} className="inngest-arrow" />
      </a>

      {run.subs && run.subs.length > 0 && (
        <Panel title="Sub-runs" sub={run.subs.length + " child task" + (run.subs.length > 1 ? "s" : "")}>
          <div className="subrun-tree">
            {run.subs.map((s) => {
              const sst = RUN_STATUS[s.status];
              return (
                <button className="subrun" key={s.id} onClick={() => onOpenRun(s.id)}>
                  <span className="subrun-branch" aria-hidden="true" />
                  <StatusDot tone={sst.token} pulse={s.status === "running"} />
                  <span className="subrun-kind">{s.kind}</span>
                  <span className="subrun-src mono">{s.source}</span>
                  <span className="subrun-id mono">#{s.id}</span>
                </button>
              );
            })}
          </div>
        </Panel>
      )}

      <Panel title="Execution logs" sub={live ? "Streaming live" : "Completed"}
        actions={live ? <span className="run-live"><span className="run-live-dot" />live</span> : null} noPad>
        <div className="exec-console">
          {run.steps.map((s, i) => (
            <div className={"log-row lvl-" + ({ INFO: "accent", DEBUG: "muted", WARNING: "warning", ERROR: "danger" }[s.lvl])} key={i}>
              <span className={"log-lvl tone-" + ({ INFO: "accent", DEBUG: "muted", WARNING: "warning", ERROR: "danger" }[s.lvl])}>{s.lvl}</span>
              <span className="log-kind">{s.kind}</span>
              <span className="log-ts mono">{offClock(s.off)}</span>
              <span className="log-msg">{s.msg}</span>
            </div>
          ))}
          {live && <div className="exec-cursor mono"><span className="exec-blink">▋</span> awaiting next step…</div>}
        </div>
      </Panel>
    </div>
  );
}

Object.assign(window, { RunsList, RunDetail, RUN_STATUS });
