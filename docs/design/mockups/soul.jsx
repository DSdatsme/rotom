// SOUL Persona — identity/style document editor. Exported to window.
const { useState: useStateSo, useEffect: useEffectSo, useRef: useRefSo } = React;

const SOUL_HINTS = [
  { icon: "info", label: "Background", hint: "Who you are, your role, what you care about." },
  { icon: "activity", label: "Tone & voice", hint: "Formal or casual? Words you love and ban." },
  { icon: "corner-down-left", label: "Situations", hint: "How you schedule, decline, deliver bad news." },
  { icon: "pencil", label: "Writing samples", hint: "A few real lines rotom can echo." },
];

function SoulPersona({ initial, onSaved }) {
  const [doc, setDoc] = useStateSo(initial);
  const [state, setState] = useStateSo("saved"); // idle | saving | saved | error
  const taRef = useRefSo(null);
  const timer = useRefSo(null);
  const first = useRefSo(true);

  // autosave-feel: debounce on edit
  useEffectSo(() => {
    if (first.current) { first.current = false; return; }
    setState("saving");
    clearTimeout(timer.current);
    timer.current = setTimeout(() => { setState("saved"); onSaved && onSaved(); }, 900);
    return () => clearTimeout(timer.current);
  }, [doc]);

  const words = doc.trim() ? doc.trim().split(/\s+/).length : 0;
  const samples = (doc.match(/^>/gm) || []).length;

  function saveNow() {
    clearTimeout(timer.current);
    setState("saving");
    setTimeout(() => { setState("saved"); onSaved && onSaved(); }, 500);
  }

  return (
    <div className="soul">
      <div className="soul-head">
        <div className="soul-head-text">
          <h1 className="page-title">SOUL Persona</h1>
          <p className="page-sub">Define your background, tone, and writing samples. rotom uses this to mimic your style perfectly.</p>
        </div>
        <div className="soul-save">
          <span className={"save-state " + state}>
            {state === "saving" && <React.Fragment><Icon name="loader" size={13} />Saving…</React.Fragment>}
            {state === "saved" && <React.Fragment><Icon name="check" size={13} />Saved</React.Fragment>}
            {state === "error" && <React.Fragment><Icon name="x-circle" size={13} />Save failed</React.Fragment>}
          </span>
          <Button variant="default" size="sm" icon="save" onClick={saveNow}>Save now</Button>
        </div>
      </div>

      <div className="soul-banner">
        <span className="soul-banner-ic"><Icon name="sparkles" size={16} /></span>
        <span>This document shapes <strong>every reply rotom writes.</strong> The more honest and specific you are about your voice, the more its drafts sound like you — not a generic assistant.</span>
      </div>

      <div className="soul-grid">
        <div className="soul-editor-wrap">
          <div className="soul-editor-bar">
            <span className="seb-label mono">persona.md</span>
            <span className="seb-stats mono">{words} words · {samples} sample{samples === 1 ? "" : "s"}</span>
          </div>
          <textarea
            ref={taRef}
            className="soul-editor"
            value={doc}
            onChange={(e) => setDoc(e.target.value)}
            spellCheck={true}
            placeholder="Start with who you are…"
          />
        </div>

        <aside className="soul-aside">
          <div className="soul-aside-title">What to include</div>
          <div className="soul-hints">
            {SOUL_HINTS.map((h) => (
              <div className="soul-hint" key={h.label}>
                <span className="soul-hint-ic"><Icon name={h.icon} size={14} /></span>
                <div className="soul-hint-text">
                  <span className="soul-hint-label">{h.label}</span>
                  <span className="soul-hint-hint">{h.hint}</span>
                </div>
              </div>
            ))}
          </div>
          <div className="soul-tip">
            <Icon name="info" size={13} />
            <span>It's free-form — these are just guides. Write it the way you'd brief a new assistant.</span>
          </div>
        </aside>
      </div>
    </div>
  );
}

Object.assign(window, { SoulPersona });
