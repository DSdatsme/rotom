// Command palette (Cmd/Ctrl-K). Fuzzy jump to pages + run quick actions + search emails.
const { useState: useStateP, useEffect: useEffectP, useRef: useRefP, useMemo: useMemoP } = React;

function fuzzy(q, text) {
  q = q.toLowerCase().trim();
  text = text.toLowerCase();
  if (!q) return 0.0001;
  if (text.includes(q)) return 100 - text.indexOf(q); // contiguous wins
  let ti = 0, score = 0, streak = 0;
  for (let qi = 0; qi < q.length; qi++) {
    const c = q[qi];
    let found = false;
    while (ti < text.length) {
      if (text[ti] === c) { streak += 1; score += 1 + streak; ti++; found = true; break; }
      ti++; streak = 0;
    }
    if (!found) return -1;
  }
  return score;
}

function CommandPalette({ open, onClose, onNavigate, onAction, onOpenEmail }) {
  const { NAV, QUICK_ACTIONS, EMAILS, CAT } = window.ROTOM;
  const [q, setQ] = useStateP("");
  const [sel, setSel] = useStateP(0);
  const inputRef = useRefP(null);
  const listRef = useRefP(null);

  const pages = useMemoP(() => NAV.flatMap((g) => g.items.map((i) => ({ ...i, group: g.label }))), [NAV]);

  // Build a flat, scored, sectioned result set
  const results = useMemoP(() => {
    const out = [];
    const pageHits = pages
      .map((p) => ({ ...p, _t: "page", _s: Math.max(fuzzy(q, p.label), fuzzy(q, p.group) - 5) }))
      .filter((p) => p._s > -1)
      .sort((a, b) => b._s - a._s);
    const actHits = QUICK_ACTIONS
      .map((a) => ({ ...a, _t: "action", _s: fuzzy(q, a.label) }))
      .filter((a) => a._s > -1)
      .sort((a, b) => b._s - a._s);
    const emailHits = (q.trim().length >= 2 ? EMAILS : [])
      .map((e) => ({ ...e, _t: "email", _s: Math.max(fuzzy(q, e.subject), fuzzy(q, e.from) - 3) }))
      .filter((e) => e._s > -1)
      .sort((a, b) => b._s - a._s)
      .slice(0, 5);

    if (actHits.length) out.push({ header: "Actions", rows: actHits });
    if (pageHits.length) out.push({ header: "Jump to", rows: pageHits });
    if (emailHits.length) out.push({ header: "Emails", rows: emailHits });
    return out;
  }, [q, pages]);

  const flat = useMemoP(() => results.flatMap((s) => s.rows), [results]);

  useEffectP(() => { setSel(0); }, [q]);
  useEffectP(() => {
    if (open) {
      setQ(""); setSel(0);
      const id = setTimeout(() => inputRef.current && inputRef.current.focus(), 20);
      return () => clearTimeout(id);
    }
  }, [open]);

  useEffectP(() => {
    if (!listRef.current) return;
    const el = listRef.current.querySelector('[data-idx="' + sel + '"]');
    if (el) el.scrollIntoView ? null : null; // avoid scrollIntoView; rely on small list
  }, [sel]);

  if (!open) return null;

  function pick(row) {
    if (!row) return;
    if (row._t === "page") onNavigate(row.id);
    else if (row._t === "action") onAction(row.id);
    else if (row._t === "email") onOpenEmail(row);
    onClose();
  }

  function onKey(e) {
    if (e.key === "Escape") { e.preventDefault(); onClose(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(s + 1, flat.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); pick(flat[sel]); }
  }

  let idx = -1;
  return (
    <div className="cmdk-overlay" onMouseDown={onClose}>
      <div className="cmdk" role="dialog" aria-label="Command palette" onMouseDown={(e) => e.stopPropagation()}>
        <div className="cmdk-input-row">
          <Icon name="search" size={17} className="cmdk-search-ic" />
          <input
            ref={inputRef}
            className="cmdk-input"
            placeholder="Search or jump to…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={onKey}
            aria-label="Command palette search"
          />
          <Kbd>Esc</Kbd>
        </div>
        <div className="cmdk-list" ref={listRef}>
          {flat.length === 0 && (
            <div className="cmdk-empty">
              <Icon name="search" size={18} />
              <span>No results for “{q}”</span>
            </div>
          )}
          {results.map((sec) => (
            <div className="cmdk-section" key={sec.header}>
              <div className="cmdk-section-label">{sec.header}</div>
              {sec.rows.map((row) => {
                idx += 1;
                const i = idx;
                const active = i === sel;
                return (
                  <button
                    key={row._t + (row.id)}
                    data-idx={i}
                    className={"cmdk-row" + (active ? " active" : "")}
                    onMouseMove={() => setSel(i)}
                    onClick={() => pick(row)}
                  >
                    <span className="cmdk-row-ic">
                      <Icon name={rowIcon(row)} size={16} />
                    </span>
                    <span className="cmdk-row-main">
                      <span className="cmdk-row-title">{rowTitle(row)}</span>
                      {rowSub(row, CAT) && <span className="cmdk-row-sub">{rowSub(row, CAT)}</span>}
                    </span>
                    {row._t === "page" && <span className="cmdk-row-tag">{row.group}</span>}
                    {row._t === "action" && row.kbd && <Kbd>{row.kbd}</Kbd>}
                    {active && <Icon name="corner-down-left" size={14} className="cmdk-row-enter" />}
                  </button>
                );
              })}
            </div>
          ))}
        </div>
        <div className="cmdk-foot">
          <span><Kbd>↑</Kbd><Kbd>↓</Kbd> navigate</span>
          <span><Kbd>↵</Kbd> select</span>
          <span><Kbd>esc</Kbd> close</span>
        </div>
      </div>
    </div>
  );
}

function rowIcon(row) {
  if (row._t === "page") return row.icon;
  if (row._t === "action") return row.icon;
  return window.ROTOM.CAT[row.cat] ? window.ROTOM.CAT[row.cat].icon : "mail";
}
function rowTitle(row) {
  if (row._t === "email") return row.subject;
  return row.label;
}
function rowSub(row, CAT) {
  if (row._t === "email") return row.from;
  if (row._t === "action") return row.hint;
  return null;
}

Object.assign(window, { CommandPalette });
