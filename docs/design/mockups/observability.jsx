// Observability — Usage & Metrics. KPI tiles + stacked-area chart + usage table. Exported to window.
const { useState: useStateO } = React;

const SERIES_COLOR = {
  "gpt-4o-mini": "var(--accent)",
  "gpt-4o": "var(--slate)",
  "claude-3.5-sonnet": "oklch(0.72 0.02 255)",
};
function fmtTok(n) { if (n >= 1e6) return (n / 1e6).toFixed(2) + "M"; if (n >= 1e3) return (n / 1e3).toFixed(1) + "K"; return "" + n; }
function fmtInt(n) { return n.toLocaleString("en-US"); }
function fmtMs(ms) { return (ms / 1000).toFixed(2) + "s"; }

/* ---------------------------------------------------------- KPI tiles */
function Kpi({ label, value, sub, icon, accent }) {
  return (
    <div className={"kpi" + (accent ? " accent" : "")}>
      <div className="kpi-top"><Icon name={icon} size={14} /><span className="kpi-label">{label}</span></div>
      <div className="kpi-value">{value}</div>
      <div className="kpi-sub">{sub}</div>
    </div>
  );
}

/* ---------------------------------------------------------- stacked area chart */
function TokensChart({ days, models }) {
  const n = days.length;
  const totals = days.map((d) => models.reduce((a, m) => a + d.m[m], 0));
  const max = Math.max(...totals, 1) * 1.12;
  const vbW = 820, vbH = 300, PADL = 6, PADR = 6, PADT = 12, PADB = 24;
  const plotW = vbW - PADL - PADR, plotH = vbH - PADT - PADB;
  const X = (i) => PADL + (n === 1 ? 0 : (i / (n - 1)) * plotW);
  const Y = (v) => PADT + plotH * (1 - v / max);

  let lower = new Array(n).fill(0);
  const bands = models.map((m) => {
    const upper = lower.map((lo, i) => lo + days[i].m[m]);
    const top = days.map((_, i) => X(i) + "," + Y(upper[i])).join(" L ");
    const bot = days.map((_, i) => X(n - 1 - i) + "," + Y(lower[n - 1 - i])).join(" L ");
    const line = "M " + days.map((_, i) => X(i) + "," + Y(upper[i])).join(" L ");
    const band = { m, path: "M " + top + " L " + bot + " Z", line };
    lower = upper;
    return band;
  });
  const grid = [0, 0.25, 0.5, 0.75, 1].map((f) => ({ y: Y(max * f), v: max * f }));
  const xticks = [0, 3, 6, 9, 12, 13].filter((i) => i < n);

  return (
    <div className="chart-wrap">
      <svg className="chart-svg" viewBox={"0 0 " + vbW + " " + vbH} preserveAspectRatio="xMidYMid meet" role="img" aria-label="Tokens over time, stacked by model">
        {grid.map((g, i) => (
          <g key={i}>
            <line x1={PADL} x2={vbW - PADR} y1={g.y} y2={g.y} stroke="var(--border)" strokeWidth="1" />
            <text x={PADL + 2} y={g.y - 4} className="chart-ylabel">{fmtTok(Math.round(g.v))}</text>
          </g>
        ))}
        {bands.map((b) => (
          <path key={b.m} d={b.path} fill={SERIES_COLOR[b.m]} fillOpacity={b.m === "gpt-4o-mini" ? 0.32 : 0.22} />
        ))}
        {bands.map((b) => (
          <path key={b.m + "l"} d={b.line} fill="none" stroke={SERIES_COLOR[b.m]} strokeWidth="2" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
        ))}
        {xticks.map((i) => (
          <text key={i} x={X(i)} y={vbH - 6} className="chart-xlabel" textAnchor={i === 0 ? "start" : i === n - 1 ? "end" : "middle"}>{days[i].d}</text>
        ))}
      </svg>
      <div className="chart-legend">
        {models.map((m) => (
          <span className="legend-item" key={m}><span className="legend-dot" style={{ background: SERIES_COLOR[m] }} />{m}</span>
        ))}
      </div>
    </div>
  );
}

function ChartSkeleton() {
  return <div className="chart-wrap"><Skeleton w="100%" h={300} r={10} /></div>;
}

/* ---------------------------------------------------------- usage table */
function UsageTable({ rows }) {
  return (
    <div className="usage-tbl-wrap">
      <table className="tbl usage-tbl">
        <colgroup><col style={{ width: "140px" }} /><col /><col style={{ width: "170px" }} /><col style={{ width: "104px" }} /><col style={{ width: "104px" }} /><col style={{ width: "118px" }} /></colgroup>
        <thead><tr><th>Date</th><th>Purpose</th><th>Model</th><th className="num">Input</th><th className="num">Output</th><th className="num">Avg latency</th></tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr className="row" key={i}>
              <td className="mono col-udate">{r.date}</td>
              <td>{r.purpose ? <span className="purpose-pill">{r.purpose}<span className="mono">#{r.runId.replace("r_", "")}</span></span> : <span className="adhoc">adhoc</span>}</td>
              <td className="mono col-model">{r.model}</td>
              <td className="num mono">{fmtInt(r.input)}</td>
              <td className="num mono">{fmtInt(r.output)}</td>
              <td className="num mono">{fmtMs(r.latency)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ---------------------------------------------------------- page */
function Observability({ loading }) {
  const { USAGE_DAYS, USAGE_ROWS, MODELS } = window.ROTOM;
  const total = USAGE_DAYS.reduce((a, d) => a + MODELS.reduce((s, m) => s + d.m[m], 0), 0);
  const input = Math.round(total * 0.79), output = total - input;
  const avgLat = Math.round(USAGE_ROWS.reduce((a, r) => a + r.latency, 0) / USAGE_ROWS.length);
  const runs = 138;

  return (
    <div className="obsv">
      <div className="obsv-head">
        <h1 className="page-title">Observability</h1>
        <p className="page-sub">Token usage across all models <span className="mono obsv-range">(Last 14 days)</span></p>
      </div>

      <div className="kpi-row">
        {loading ? [0, 1, 2, 3, 4].map((i) => <div className="kpi skel" key={i}><Skeleton w="60%" h={11} /><Skeleton w="50%" h={24} style={{ margin: "10px 0 6px" }} /><Skeleton w="40%" h={10} /></div>)
          : <React.Fragment>
            <Kpi label="Total tokens" value={fmtTok(total)} sub="14-day window" icon="hash" accent />
            <Kpi label="Input" value={fmtTok(input)} sub="79% of total" icon="arrow-down" />
            <Kpi label="Output" value={fmtTok(output)} sub="21% of total" icon="arrow-up" />
            <Kpi label="Avg latency" value={fmtMs(avgLat)} sub="across runs" icon="gauge" />
            <Kpi label="Runs" value={fmtInt(runs)} sub="14-day window" icon="zap2" />
          </React.Fragment>}
      </div>

      <Panel title="Tokens over time" sub="Stacked by model">
        {loading ? <ChartSkeleton /> : <TokensChart days={USAGE_DAYS} models={MODELS} />}
      </Panel>

      <Panel title="Usage log" sub="Per-run token accounting" noPad>
        {loading ? (
          <div style={{ padding: "var(--pad)" }}>{[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} w="100%" h={28} style={{ marginBottom: 8 }} />)}</div>
        ) : USAGE_ROWS.length === 0 ? (
          <EmptyState icon="bar-chart" title="No usage data recorded yet" body="Token accounting will appear here after the assistant runs." />
        ) : (
          <UsageTable rows={USAGE_ROWS} />
        )}
      </Panel>
    </div>
  );
}

Object.assign(window, { Observability });
