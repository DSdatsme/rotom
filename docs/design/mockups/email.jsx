// Inbox triage (list) + Email detail. Exported to window.
const { useState: useStateE, useEffect: useEffectE, useRef: useRefE, useMemo: useMemoE } = React;

/* ----------------------------------------------------- badges + scales */
function CategoryBadge({ cat }) {
  const c = window.ROTOM.CAT[cat];
  if (!c) return null;
  return (
    <span className={"cat-badge tone-" + c.token}>
      <Icon name={c.icon} size={12} />
      {c.label}
    </span>
  );
}
function InjectionBadge({ compact }) {
  const inj = window.ROTOM.INJECTION;
  return (
    <span className="inj-badge" title="Possible prompt injection — handle with care">
      <Icon name={inj.icon} size={12} />
      {!compact && inj.label}
    </span>
  );
}
function StatusBadge({ status }) {
  const s = window.ROTOM.STATUS[status];
  if (!s) return null;
  return (
    <span className={"status-badge tone-" + s.token}>
      <Icon name={s.icon} size={12} />
      {s.label}
    </span>
  );
}
function UrgencyScale({ level }) {
  const n = window.ROTOM.URGENCY[level] || 0;
  return (
    <span className={"urg lvl-" + level} title={"Urgency: " + level} aria-label={"Urgency " + level}>
      {[1, 2, 3].map((i) => (
        <span key={i} className={"urg-seg" + (i <= n ? " on" : "")} />
      ))}
    </span>
  );
}

/* ----------------------------------------------------- date helpers */
function recvDays(e) {
  const m = { "Jun 14": 0, "Jun 13": 1, "Jun 12": 2, "Jun 11": 3 };
  return m[e.dateEmail] != null ? m[e.dateEmail] : 99;
}
function triagedHours(s) {
  if (/m ago|just/.test(s)) return 0.2;
  const h = /(\d+)\s*h/.exec(s);
  if (h) return +h[1];
  if (/yesterday/.test(s)) return 26;
  const d = /(\d+)\s*day/.exec(s);
  if (d) return +d[1] * 24;
  return 0.2;
}

/* ----------------------------------------------------- facet dropdown */
function Facet({ label, icon, options, value, onChange, multi = true }) {
  const [open, setOpen] = useStateE(false);
  const ref = useRefE(null);
  useEffectE(() => {
    if (!open) return;
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [open]);
  const active = multi ? value.length > 0 : value !== options[0].id;
  const summary = multi
    ? (value.length === 0 ? null : value.length)
    : (active ? options.find((o) => o.id === value).label : null);
  function toggle(id) {
    if (multi) onChange(value.includes(id) ? value.filter((v) => v !== id) : [...value, id]);
    else { onChange(id); setOpen(false); }
  }
  return (
    <div className="facet-wrap" ref={ref}>
      <button className={"facet" + (active ? " active" : "")} onClick={() => setOpen((o) => !o)}>
        <Icon name={icon} size={13} />
        <span>{label}</span>
        {summary != null && <span className="facet-count">{summary}</span>}
        <Icon name="chevron-down" size={13} className="facet-caret" />
      </button>
      {open && (
        <div className="facet-pop">
          {options.map((o) => {
            const on = multi ? value.includes(o.id) : value === o.id;
            return (
              <button key={o.id} className="facet-opt" onClick={() => toggle(o.id)}>
                <span className={"facet-check" + (on ? " on" : "")}>
                  {on && <Icon name="check" size={11} />}
                </span>
                {o.swatch && <span className={"facet-swatch tone-" + o.swatch} />}
                <span className="facet-opt-label">{o.label}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

/* ----------------------------------------------------- filter bar */
const DEFAULT_FILTERS = { category: ["critical", "needs_reply"], status: ["open"], accounts: [], urgency: [], suspicious: false, received: "any", triaged: "any" };

function FilterBar({ filters, setFilters }) {
  const { ACCOUNTS } = window.ROTOM;
  const catOpts = [
    { id: "critical", label: "Critical", swatch: "danger" },
    { id: "needs_reply", label: "Needs reply", swatch: "accent" },
    { id: "fyi", label: "FYI", swatch: "slate" },
    { id: "skip", label: "Skip", swatch: "muted" },
  ];
  const statusOpts = [
    { id: "open", label: "Open", swatch: "accent" },
    { id: "done", label: "Done", swatch: "success" },
    { id: "irrelevant", label: "Irrelevant", swatch: "muted" },
  ];
  const urgOpts = [
    { id: "high", label: "High" }, { id: "medium", label: "Medium" }, { id: "low", label: "Low" }, { id: "none", label: "None" },
  ];
  const acctOpts = ACCOUNTS.map((a) => ({ id: a, label: a }));
  const recvOpts = [
    { id: "any", label: "Any time" }, { id: "today", label: "Today" }, { id: "3d", label: "Last 3 days" }, { id: "7d", label: "Last 7 days" },
  ];
  const triOpts = [
    { id: "any", label: "Any time" }, { id: "1h", label: "Last hour" }, { id: "24h", label: "Last 24 hours" }, { id: "week", label: "This week" },
  ];
  const set = (k) => (v) => setFilters((f) => ({ ...f, [k]: v }));
  const dirty = JSON.stringify(filters) !== JSON.stringify(DEFAULT_FILTERS);
  return (
    <div className="filter-bar">
      <Facet label="Category" icon="filter" options={catOpts} value={filters.category} onChange={set("category")} />
      <Facet label="Status" icon="circle-dot" options={statusOpts} value={filters.status} onChange={set("status")} />
      <Facet label="Account" icon="at-sign" options={acctOpts} value={filters.accounts} onChange={set("accounts")} />
      <Facet label="Urgency" icon="sliders" options={urgOpts} value={filters.urgency} onChange={set("urgency")} />
      <Facet label="Received" icon="calendar" options={recvOpts} value={filters.received} onChange={set("received")} multi={false} />
      <Facet label="Triaged" icon="clock" options={triOpts} value={filters.triaged} onChange={set("triaged")} multi={false} />
      <button className={"susp-toggle" + (filters.suspicious ? " active" : "")} onClick={() => setFilters((f) => ({ ...f, suspicious: !f.suspicious }))}>
        <Icon name="shield" size={13} />
        <span>Suspicious only</span>
      </button>
      {dirty && (
        <button className="filter-reset" onClick={() => setFilters(DEFAULT_FILTERS)}>
          <Icon name="x-circle" size={13} />
          <span>Reset</span>
        </button>
      )}
    </div>
  );
}

/* ----------------------------------------------------- table rows */
function applyFilters(emails, f) {
  const recvMax = { any: Infinity, today: 0, "3d": 2, "7d": 6 }[f.received];
  const triMax = { any: Infinity, "1h": 1, "24h": 24, week: 168 }[f.triaged];
  return emails.filter((e) => {
    if (f.category.length && !f.category.includes(e.cat)) return false;
    if (f.status.length && !f.status.includes(e.status)) return false;
    if (f.accounts.length && !f.accounts.includes(e.account)) return false;
    if (f.urgency.length && !f.urgency.includes(e.urgency)) return false;
    if (f.suspicious && !e.injection) return false;
    if (recvDays(e) > recvMax) return false;
    if (triagedHours(e.triaged) > triMax) return false;
    return true;
  });
}

function TriageRow({ e, idx, selected, cursor, onToggle, onOpen, onCursor }) {
  return (
    <tr
      className={"row" + (selected ? " selected" : "") + (cursor ? " cursor" : "")}
      onMouseEnter={() => onCursor(idx)}
    >
      <td className="col-check" onClick={(ev) => { ev.stopPropagation(); onToggle(e.id); }}>
        <span className={"checkbox" + (selected ? " on" : "")}>{selected && <Icon name="check" size={12} />}</span>
      </td>
      <td className="col-acct mono">{e.account}</td>
      <td className="col-subj">
        <button className="subj-link" onClick={() => onOpen(e.id)}>{e.subject}</button>
      </td>
      <td className="col-from">
        <span className="from-name">{e.fromName}</span>
        <span className="from-addr mono">{e.from}</span>
      </td>
      <td className="col-cat">
        <span className="cat-cell">
          <CategoryBadge cat={e.cat} />
          {e.injection && <InjectionBadge compact />}
        </span>
      </td>
      <td className="col-status"><StatusBadge status={e.status} /></td>
      <td className="col-urg"><UrgencyScale level={e.urgency} /></td>
      <td className="col-date mono">{e.dateEmail}<span className="date-time">{e.timeEmail}</span></td>
      <td className="col-triaged mono">{e.triaged}</td>
    </tr>
  );
}

function TableSkeleton() {
  return (
    <tbody>
      {Array.from({ length: 8 }).map((_, i) => (
        <tr className="row skel" key={i}>
          <td className="col-check"><Skeleton w={16} h={16} r={4} /></td>
          <td className="col-acct"><Skeleton w="80px" h={11} /></td>
          <td className="col-subj"><Skeleton w={i % 2 ? "70%" : "52%"} h={12} /></td>
          <td className="col-from"><Skeleton w="60%" h={11} /></td>
          <td className="col-cat"><Skeleton w="84px" h={18} r={9} /></td>
          <td className="col-status"><Skeleton w="58px" h={18} r={9} /></td>
          <td className="col-urg"><Skeleton w="26px" h={10} /></td>
          <td className="col-date"><Skeleton w="44px" h={11} /></td>
          <td className="col-triaged"><Skeleton w="40px" h={11} /></td>
        </tr>
      ))}
    </tbody>
  );
}

/* ----------------------------------------------------- inbox triage page */
function InboxTriage({ emails, loading, enabled, onOpen, onBulk }) {
  const [filters, setFilters] = useStateE(DEFAULT_FILTERS);
  const [sel, setSel] = useStateE(() => new Set());
  const [cursor, setCursor] = useStateE(0);

  const rows = useMemoE(() => applyFilters(emails, filters), [emails, filters]);
  useEffectE(() => { setCursor((c) => Math.min(c, Math.max(0, rows.length - 1))); }, [rows.length]);
  // drop selections no longer visible
  useEffectE(() => {
    setSel((s) => {
      const visible = new Set(rows.map((r) => r.id));
      const next = new Set([...s].filter((id) => visible.has(id)));
      return next.size === s.size ? s : next;
    });
  }, [rows]);

  const toggle = (id) => setSel((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const allOn = rows.length > 0 && rows.every((r) => sel.has(r.id));
  const someOn = sel.size > 0 && !allOn;
  const toggleAll = () => setSel(() => (allOn ? new Set() : new Set(rows.map((r) => r.id))));
  const clearSel = () => setSel(new Set());

  function bulk(action) {
    const ids = [...sel];
    onBulk(ids, action);
    clearSel();
  }

  // j/k row navigation + x select + e mark done + enter open
  useEffectE(() => {
    if (!enabled) return;
    function onKey(ev) {
      const typing = /^(input|textarea|select)$/i.test((ev.target.tagName || "")) || ev.target.isContentEditable;
      if (typing || ev.metaKey || ev.ctrlKey || ev.altKey) return;
      const k = ev.key.toLowerCase();
      if (k === "j") { ev.preventDefault(); setCursor((c) => Math.min(c + 1, rows.length - 1)); }
      else if (k === "k") { ev.preventDefault(); setCursor((c) => Math.max(c - 1, 0)); }
      else if (k === "x") { ev.preventDefault(); const r = rows[cursor]; if (r) toggle(r.id); }
      else if (k === "enter") { const r = rows[cursor]; if (r) onOpen(r.id); }
      else if (k === "e") { const r = rows[cursor]; if (r) { onBulk([r.id], "done"); } }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [enabled, rows, cursor]);

  return (
    <div className="triage">
      <div className="triage-head">
        <div className="triage-title-wrap">
          <h1 className="page-title">Inbox triage</h1>
          <p className="count-line"><span className="mono">{rows.length}</span> {rows.length === 1 ? "email" : "emails"}</p>
        </div>
        <div className="triage-head-actions">
          <span className="kbd-hint"><Kbd>j</Kbd><Kbd>k</Kbd> move · <Kbd>x</Kbd> select · <Kbd>e</Kbd> done</span>
        </div>
      </div>

      <FilterBar filters={filters} setFilters={setFilters} />

      <div className="tbl-wrap">
        <table className="tbl">
          <colgroup>
            <col style={{ width: "38px" }} /><col style={{ width: "150px" }} /><col /><col style={{ width: "180px" }} />
            <col style={{ width: "188px" }} /><col style={{ width: "104px" }} /><col style={{ width: "58px" }} /><col style={{ width: "82px" }} /><col style={{ width: "92px" }} />
          </colgroup>
          <thead>
            <tr>
              <th className="col-check" onClick={toggleAll}>
                <span className={"checkbox" + (allOn ? " on" : "") + (someOn ? " some" : "")}>
                  {allOn && <Icon name="check" size={12} />}
                  {someOn && <Icon name="minus" size={12} />}
                </span>
              </th>
              <th>Account</th><th>Subject</th><th>From</th><th>Category</th><th>Status</th><th>Urg.</th><th>Email date</th><th>Triaged</th>
            </tr>
          </thead>
          {loading ? (
            <TableSkeleton />
          ) : (
            <tbody>
              {rows.map((e, i) => (
                <TriageRow key={e.id} e={e} idx={i} selected={sel.has(e.id)} cursor={i === cursor}
                  onToggle={toggle} onOpen={onOpen} onCursor={setCursor} />
              ))}
            </tbody>
          )}
        </table>
        {!loading && rows.length === 0 && (
          <EmptyState icon="inbox" title="No emails match these filters"
            body="Try widening the category or status filters, or reset to the default triage view."
            action={<Button size="sm" icon="x-circle" onClick={() => setFilters(DEFAULT_FILTERS)}>Reset filters</Button>} />
        )}
      </div>

      {sel.size > 0 && (
        <div className="bulk-bar" role="toolbar" aria-label="Bulk actions">
          <span className="bulk-info"><span className="mono">{sel.size}</span> selected</span>
          <div className="bulk-sep" />
          <button className="bulk-act" onClick={() => bulk("done")}><Icon name="circle-check" size={14} />Mark done</button>
          <button className="bulk-act" onClick={() => bulk("irrelevant")}><Icon name="circle-slash" size={14} />Mark irrelevant</button>
          <button className="bulk-act" onClick={() => bulk("open")}><Icon name="circle-dot" size={14} />Reopen</button>
          <button className="bulk-clear" onClick={clearSel} aria-label="Clear selection"><Icon name="x" size={15} /></button>
        </div>
      )}
    </div>
  );
}

/* ----------------------------------------------------- email detail page */
function StatusActions({ status, onStatus }) {
  const opts = [
    { id: "open", label: "Open", icon: "circle-dot" },
    { id: "done", label: "Done", icon: "circle-check" },
    { id: "irrelevant", label: "Irrelevant", icon: "circle-slash" },
  ];
  return (
    <div className="status-actions" role="group" aria-label="Set status">
      {opts.map((o) => (
        <button key={o.id} className={"status-act" + (status === o.id ? " active tone-" + window.ROTOM.STATUS[o.id].token : "")} onClick={() => onStatus(o.id)}>
          <Icon name={o.icon} size={14} />
          <span>{o.label}</span>
        </button>
      ))}
    </div>
  );
}

function EmailDetail({ email, draft, onStatus, onOpenComposer, onDiscardDraft }) {
  if (!email) return null;
  const u = email.urgency;
  return (
    <div className="edetail">
      <div className="ed-head">
        <h1 className="ed-subject">{email.subject}</h1>
        <p className="ed-meta">
          from <span className="ed-from">{email.fromName}</span>
          <span className="mono"> &lt;{email.from}&gt;</span>
          <span className="ed-dot">·</span><span className="mono">{email.account}</span>
          <span className="ed-dot">·</span><span className="mono">{email.dateEmail}, {email.timeEmail}</span>
        </p>
        <div className="ed-badges">
          <CategoryBadge cat={email.cat} />
          {email.injection && <InjectionBadge />}
          <span className="urg-badge">Urgency:&nbsp;<UrgencyScale level={u} /><span className="urg-word">{u}</span></span>
          <StatusBadge status={email.status} />
        </div>
        <div className="ed-actions">
          <StatusActions status={email.status} onStatus={onStatus} />
        </div>
      </div>

      <div className={"ed-reason" + (email.injection ? " danger" : "")}>
        <span className="ed-reason-ic"><Icon name={email.injection ? "shield" : "sparkles"} size={15} /></span>
        <div className="ed-reason-text">
          <span className="ed-reason-label">{email.injection ? "Why rotom flagged this as suspicious" : "Why rotom flagged this"}</span>
          <span className="ed-reason-body">{email.reason}</span>
        </div>
      </div>

      <Panel title="Email content">
        <div className={"ed-body" + (email.injection ? " quarantined" : "")}>
          {email.injection && (
            <div className="quarantine-note"><Icon name="shield" size={13} /> Links and embedded instructions are disabled while this message is flagged.</div>
          )}
          {email.body.split("\n\n").map((p, i) => <p key={i}>{p}</p>)}
        </div>
      </Panel>

      <Panel
        title="Reply draft"
        sub={draft ? "rotom drafted a reply — awaiting your review" : "No pending draft for this email"}
        actions={<button className="link-btn" onClick={() => onOpenComposer(email.id)}><Icon name="refresh" size={13} />{draft ? "Regenerate" : "Generate draft"}</button>}
      >
        {draft ? (
          <div className="ed-draft">
            <div className="ed-draft-to mono">To: {draft.to}</div>
            <div className="ed-draft-body">{draft.body.split("\n\n").map((p, i) => <p key={i}>{p}</p>)}</div>
            <div className="ed-draft-actions">
              <Button variant="primary" size="sm" icon="pencil" onClick={() => onOpenComposer(email.id)}>Edit &amp; send</Button>
              <Button variant="ghost" size="sm" icon="trash" onClick={() => onDiscardDraft(draft.id)}>Discard</Button>
            </div>
          </div>
        ) : (
          <EmptyState icon="pencil" title="No reply drafted yet"
            body="Generate an AI-assisted reply and review it before anything is sent."
            action={<Button size="sm" icon="sparkles" onClick={() => onOpenComposer(email.id)}>Generate draft</Button>} />
        )}
      </Panel>
    </div>
  );
}

Object.assign(window, { InboxTriage, EmailDetail, CategoryBadge, InjectionBadge, StatusBadge, UrgencyScale });
