// Reminders board + natural-language chat bar. Exported to window.
const { useState: useStateR, useEffect: useEffectR, useRef: useRefR } = React;

/* ---------------------------------------------------------- time helpers */
function fmtCountdown(ms) {
  if (ms == null) return "—";
  if (ms <= 0) return "due now";
  const s = Math.floor(ms / 1000);
  const d = Math.floor(s / 86400), h = Math.floor(s / 3600) % 24, m = Math.floor(s / 60) % 60, sec = s % 60;
  const p = (n) => String(n).padStart(2, "0");
  return (d > 0 ? d + "d " : "") + p(h) + ":" + p(m) + ":" + p(sec);
}
function fmtAbs(fireAt) {
  if (fireAt == null) return "No time set";
  const d = new Date(fireAt), now = new Date();
  const p = (n) => String(n).padStart(2, "0");
  const hm = p(d.getHours()) + ":" + p(d.getMinutes());
  const sameDay = d.toDateString() === now.toDateString();
  const tmr = new Date(now); tmr.setDate(now.getDate() + 1);
  if (sameDay) return "Today " + hm;
  if (d.toDateString() === tmr.toDateString()) return "Tomorrow " + hm;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" }) + " " + hm;
}
function urgencyOf(ms) {
  if (ms == null) return "none";
  if (ms <= 0) return "due";
  if (ms < 60 * 60 * 1000) return "soon";
  return "ok";
}

/* ---------------------------------------------------------- NL parse */
function capitalize(s) { return s ? s[0].toUpperCase() + s.slice(1) : s; }
function parseNL(raw) {
  const lower = raw.toLowerCase();
  let hour = 9, min = 0, hasTime = false;
  const tm = /(\d{1,2})(?::(\d{2}))?\s*(am|pm)/.exec(lower);
  if (tm) { hour = (+tm[1] % 12) + (tm[3] === "pm" ? 12 : 0); min = tm[2] ? +tm[2] : 0; hasTime = true; }
  let day = /tomorrow/.test(lower) ? 1 : (/today|tonight/.test(lower) ? 0 : (hasTime ? 0 : 1));
  const d = new Date(); d.setDate(d.getDate() + day); d.setHours(hour, min, 0, 0);
  if (d.getTime() <= Date.now()) d.setDate(d.getDate() + 1);
  const p = (n) => String(n).padStart(2, "0");
  const hm = p(hour) + ":" + p(min);
  let cron = null;
  if (/every day|daily|each day/.test(lower)) cron = "Daily · " + hm;
  else { const wk = /every (monday|tuesday|wednesday|thursday|friday|saturday|sunday|week|morning)/.exec(lower); if (wk) cron = "Weekly · " + hm; }
  let label = raw.replace(/^\s*remind me (to |that |about )?/i, "").replace(/\s*(every day|daily|each day|every \w+)/i, "").replace(/\s*(tomorrow|today|tonight)\b/i, "").replace(/\s*at \d{1,2}(:\d{2})?\s*(am|pm)/i, "").trim();
  if (!label) label = raw.trim();
  return { text: capitalize(label), fireAt: d.getTime(), cron, when: fmtAbs(d.getTime()) };
}

/* ---------------------------------------------------------- tile */
function ReminderTile({ r, now, onCancel }) {
  const ms = r.fireAt == null ? null : r.fireAt - now;
  const u = urgencyOf(ms);
  return (
    <div className={"rem-tile urg-" + u}>
      <div className="rt-top">
        <span className="rt-text">{r.text}</span>
        <button className="rt-cancel" title="Cancel reminder" onClick={() => onCancel(r.id)}><Icon name="x" size={14} /></button>
      </div>
      <div className="rt-count mono">{fmtCountdown(ms)}</div>
      <div className="rt-meta">
        <span className="rt-fire mono"><Icon name="alarm-clock" size={12} />{fmtAbs(r.fireAt)}</span>
        {r.cron
          ? <span className="rt-cron"><Icon name="repeat" size={11} />{r.cron}</span>
          : <span className="rt-once">One-time</span>}
      </div>
    </div>
  );
}

function AddTile({ onAdd }) {
  const [open, setOpen] = useStateR(false);
  const [text, setText] = useStateR("");
  const [when, setWhen] = useStateR("");
  const [repeat, setRepeat] = useStateR("");
  function submit() {
    if (!text.trim()) return;
    const fireAt = when ? new Date(when).getTime() : null;
    onAdd({ text: text.trim(), fireAt, cron: repeat.trim() || null });
    setText(""); setWhen(""); setRepeat(""); setOpen(false);
  }
  if (!open) {
    return (
      <button className="rem-add" onClick={() => setOpen(true)}>
        <span className="rem-add-ic"><Icon name="plus" size={18} /></span>
        <span className="rem-add-label">New reminder</span>
      </button>
    );
  }
  return (
    <div className="rem-tile rem-form">
      <input className="rf-input" autoFocus placeholder="Remind me to…" value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") submit(); }} />
      <label className="rf-field"><span className="rf-key">When</span>
        <input type="datetime-local" className="rf-when mono" value={when} onChange={(e) => setWhen(e.target.value)} />
      </label>
      <label className="rf-field"><span className="rf-key">Repeat</span>
        <input className="rf-input sm" placeholder="e.g. Daily · 09:00" value={repeat} onChange={(e) => setRepeat(e.target.value)} />
      </label>
      <div className="rf-actions">
        <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>Cancel</Button>
        <Button variant="primary" size="sm" icon="plus" onClick={submit}>Add</Button>
      </div>
    </div>
  );
}

function ReminderSkeleton() {
  return (
    <div className="rem-tile skel">
      <div className="rt-top"><Skeleton w="65%" h={13} /></div>
      <Skeleton w="120px" h={26} r={6} style={{ margin: "10px 0" }} />
      <Skeleton w="80%" h={11} />
    </div>
  );
}

/* ---------------------------------------------------------- chat bar */
function ReminderChatBar({ onConfirm }) {
  const [input, setInput] = useStateR("");
  const [proposal, setProposal] = useStateR(null);
  function propose() {
    if (!input.trim()) return;
    setProposal(parseNL(input));
    setInput("");
  }
  return (
    <div className="rem-chatbar">
      {proposal && (
        <div className="proposal">
          <span className="proposal-ic"><Icon name="alarm-clock" size={16} /></span>
          <div className="proposal-body">
            <div className="proposal-text">{proposal.text}</div>
            <div className="proposal-meta mono">
              <span><Icon name="clock" size={11} />{proposal.when}</span>
              {proposal.cron && <span><Icon name="repeat" size={11} />{proposal.cron}</span>}
            </div>
            <div className="proposal-note">You confirm before anything is scheduled.</div>
          </div>
          <div className="proposal-actions">
            <Button variant="ghost" size="sm" onClick={() => setProposal(null)}>Discard</Button>
            <Button variant="primary" size="sm" icon="check" onClick={() => { onConfirm({ text: proposal.text, fireAt: proposal.fireAt, cron: proposal.cron }); setProposal(null); }}>Confirm</Button>
          </div>
        </div>
      )}
      <div className="chatbar-input">
        <Icon name="sparkles" size={16} className="chatbar-ic" />
        <input className="chatbar-field" placeholder="remind me to call mom tomorrow at 3pm…" value={input}
          onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") propose(); }} />
        <Button variant="primary" size="sm" icon="arrow-up" onClick={propose} disabled={!input.trim()}>Propose</Button>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------- page */
function Reminders({ reminders, loading, onCancel, onAdd }) {
  const [now, setNow] = useStateR(() => Date.now());
  useEffectR(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="reminders">
      <div className="reminders-head">
        <h1 className="page-title">Reminders</h1>
        <p className="page-sub">Fired to your Telegram chat. Add with the + tile or describe one below.</p>
      </div>

      {loading ? (
        <div className="rem-grid">{[0, 1, 2, 3, 4].map((i) => <ReminderSkeleton key={i} />)}</div>
      ) : reminders.length === 0 ? (
        <Panel>
          <EmptyState icon="alarm-clock" title="No reminders yet"
            body="Add one with the + tile, or just tell rotom below — “remind me to call mom tomorrow at 3pm.”" />
        </Panel>
      ) : (
        <div className="rem-grid">
          {reminders.map((r) => <ReminderTile key={r.id} r={r} now={now} onCancel={onCancel} />)}
          <AddTile onAdd={onAdd} />
        </div>
      )}

      <ReminderChatBar onConfirm={onAdd} />
    </div>
  );
}

Object.assign(window, { Reminders });
