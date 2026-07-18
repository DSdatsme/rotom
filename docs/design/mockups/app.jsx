// rotom — app root: tweaks, routing, keyboard, toasts. Mounts everything.
const { useState: useStateA, useEffect: useEffectA, useRef: useRefA, useCallback: useCallbackA } = React;
const { useTweaks, TweaksPanel, TweakSection, TweakRadio, TweakToggle, TweakSelect } = window;
const { Sidebar, TopBar, Home, ComingSoon, CommandPalette, Toaster } = window;
const { InboxTriage, EmailDetail } = window;
const { DraftsList, DraftComposer } = window;
const { Reminders, Observability, LogsExplorer } = window;
const { RunsList, RunDetail, SoulPersona } = window;

const ACCENTS = {
  Indigo: "oklch(0.62 0.13 274)",
  Violet: "oklch(0.62 0.14 295)",
  Blue: "oklch(0.64 0.13 245)",
};

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "accent": "Violet",
  "tint": "Pure neutral",
  "density": "Compact",
  "homeLayout": "Stats-forward",
  "indicator": "Bar",
  "homeState": "Ready"
}/*EDITMODE-END*/;

function pageForRoute(route) {
  const { NAV } = window.ROTOM;
  for (const g of NAV) for (const it of g.items) if (it.id === route) return it;
  return window.ROTOM.NAV[0].items[0];
}

function App() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const [route, setRoute] = useStateA("home");
  const [collapsed, setCollapsed] = useStateA(false);
  const [paletteOpen, setPaletteOpen] = useStateA(false);
  const [toasts, setToasts] = useStateA([]);
  const [loaded, setLoaded] = useStateA(false);
  const [emails, setEmails] = useStateA(() => window.ROTOM.EMAILS.map((e) => ({ ...e })));
  const [emailId, setEmailId] = useStateA(null);
  const [drafts, setDrafts] = useStateA(() => window.ROTOM.DRAFTS.map((d) => ({ ...d })));
  const [draftId, setDraftId] = useStateA(null);
  const [lastSent, setLastSent] = useStateA(null);
  const [reminders, setReminders] = useStateA(() => window.ROTOM.REMINDERS.map((r) => ({ ...r, fireAt: r.offset == null ? null : Date.now() + r.offset * 1000 })));
  const [runs] = useStateA(() => window.ROTOM.RUNS.map((r) => ({ ...r, _start: Date.now() - r.relSec * 1000 })));
  const [runId, setRunId] = useStateA(null);
  const [now, setNow] = useStateA(() => Date.now());
  const gKey = useRefA(false);
  const currentRun = runId ? runs.find((r) => r.id === runId) : null;
  const anyRunning = runs.some((r) => r.status === "running");
  const currentEmail = emailId ? emails.find((e) => e.id === emailId) : null;
  const currentDraft = draftId ? drafts.find((d) => d.id === draftId) : null;

  // poll-tick (4s) while any run is running — drives live duration + "running Ns"
  useEffectA(() => {
    if (!anyRunning) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [anyRunning]);
  useEffectA(() => {
    const id = setTimeout(() => setLoaded(true), 650);
    return () => clearTimeout(id);
  }, []);

  // apply tweak tokens to root
  useEffectA(() => {
    const r = document.documentElement;
    r.style.setProperty("--accent", ACCENTS[t.accent] || ACCENTS.Indigo);
    r.style.setProperty("--n-c", t.tint === "Pure neutral" ? "0" : "0.005");
    r.dataset.density = (t.density || "Compact").toLowerCase();
  }, [t.accent, t.tint, t.density]);

  const toast = useCallbackA((msg, opts = {}) => {
    const id = Math.random().toString(36).slice(2);
    setToasts((ts) => [...ts, { id, msg, ...opts }]);
    setTimeout(() => setToasts((ts) => ts.filter((x) => x.id !== id)), 2600);
  }, []);

  const navigate = useCallbackA((id) => { setRoute(id); setEmailId(null); setDraftId(null); setRunId(null); }, []);
  const openDetail = useCallbackA((id) => { setRoute("inbox"); setEmailId(id); }, []);
  const openDraft = useCallbackA((id) => { setRoute("drafts"); setEmailId(null); setDraftId(id); }, []);
  const openRun = useCallbackA((id) => { setRoute("runs"); setRunId(id); }, []);

  const statusIcon = (s) => (s === "done" ? "circle-check" : s === "irrelevant" ? "circle-slash" : "circle-dot");
  const setStatus = useCallbackA((id, status) => {
    setEmails((es) => es.map((e) => (e.id === id ? { ...e, status } : e)));
    toast("Marked " + status, { icon: statusIcon(status) });
  }, [toast]);
  const bulkUpdate = useCallbackA((ids, action) => {
    setEmails((es) => es.map((e) => (ids.includes(e.id) ? { ...e, status: action } : e)));
    toast(ids.length + (ids.length === 1 ? " email" : " emails") + " marked " + action, { icon: statusIcon(action) });
  }, [toast]);

  const discardDraft = useCallbackA((id) => {
    setDrafts((ds) => ds.filter((d) => d.id !== id));
    setDraftId((cur) => (cur === id ? null : cur));
    setRoute((r) => r);
    if (draftId === id) setRoute("drafts");
    toast("Draft discarded", { icon: "trash" });
  }, [toast, draftId]);

  const openComposer = useCallbackA((eid) => {
    const existing = drafts.find((d) => d.emailId === eid);
    if (existing) { openDraft(existing.id); return; }
    const em = emails.find((e) => e.id === eid);
    const nd = { id: "d" + Date.now(), type: "reply", emailId: eid, subject: "Re: " + (em ? em.subject : ""), cat: em ? em.cat : "needs_reply", to: em ? em.from : "", recipientName: em ? em.fromName : "", account: em ? em.account : window.ROTOM.ACCOUNTS[0], updated: "just now", footer: false, body: "", chat: [{ role: "rotom", text: "Tell me what you'd like to say and I'll draft it." }], attachments: [] };
    setDrafts((ds) => [nd, ...ds]);
    openDraft(nd.id);
  }, [drafts, emails, openDraft]);

  const newOutreach = useCallbackA(() => {
    const nd = { id: "o" + Date.now(), type: "outreach", emailId: null, subject: "", cat: null, to: "", recipientName: "", account: window.ROTOM.ACCOUNTS[0], updated: "just now", footer: false, body: "", chat: [{ role: "rotom", text: "Who's this going to, and what's the gist? I'll draft it." }], attachments: [] };
    setDrafts((ds) => [nd, ...ds]);
    openDraft(nd.id);
  }, [openDraft]);

  const sendDraft = useCallbackA((d) => {
    setDrafts((ds) => ds.filter((x) => x.id !== d.id));
    setLastSent(d.subject || "(no subject)");
    setRoute("drafts"); setDraftId(null); setEmailId(null);
    toast("Sent — “" + (d.subject || "draft") + "”", { icon: "send" });
  }, [toast]);
  const saveDraftLocal = useCallbackA(() => toast("Saved to this device", { icon: "save" }), [toast]);
  const saveDraftGmail = useCallbackA(() => toast("Saved to Gmail drafts", { icon: "cloud" }), [toast]);

  const addReminder = useCallbackA((r) => {
    const nr = { id: "rm" + Date.now(), text: r.text, fireAt: r.fireAt != null ? r.fireAt : null, cron: r.cron || null, channel: "Telegram", offset: null };
    setReminders((rs) => [nr, ...rs]);
    toast("Reminder scheduled", { icon: "alarm-clock" });
  }, [toast]);
  const cancelReminder = useCallbackA((id) => {
    setReminders((rs) => rs.filter((x) => x.id !== id));
    toast("Reminder cancelled", { icon: "x" });
  }, [toast]);
  const triggerRun = useCallbackA(() => { navigate("runs"); toast("Triage run started", { icon: "zap" }); }, [toast, navigate]);

  const runAction = useCallbackA((id) => {
    if (id === "triage") { navigate("runs"); toast("Triage run started", { icon: "zap", tone: "default" }); }
    else if (id === "draft") { newOutreach(); }
    else if (id === "reminder") { navigate("reminders"); toast("Add a reminder below", { icon: "bell", tone: "default" }); }
    else if (id === "search") setPaletteOpen(true);
  }, [toast, navigate, newOutreach]);

  const openEmail = useCallbackA((e) => { openDetail(e.id); }, [openDetail]);

  // global keyboard: Cmd-K, Cmd-\, g-then-key
  useEffectA(() => {
    function onKey(e) {
      const typing = /^(input|textarea|select)$/i.test((e.target.tagName || "")) || e.target.isContentEditable;
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key.toLowerCase() === "k") { e.preventDefault(); setPaletteOpen((o) => !o); return; }
      if (mod && e.key === "\\") { e.preventDefault(); setCollapsed((c) => !c); return; }
      if (e.key === "Escape" && paletteOpen) { setPaletteOpen(false); return; }
      if (typing) return;
      if (e.key === "g" && !mod) { gKey.current = true; setTimeout(() => (gKey.current = false), 700); return; }
      if (gKey.current && !mod) {
        const map = { h: "home", i: "inbox", d: "drafts", r: "reminders", u: "usage", l: "logs", s: "soul", n: "runs" };
        if (map[e.key.toLowerCase()]) { e.preventDefault(); navigate(map[e.key.toLowerCase()]); gKey.current = false; }
        return;
      }
      if (!paletteOpen && !mod) {
        if (e.key.toLowerCase() === "t") { e.preventDefault(); runAction("triage"); }
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [paletteOpen, runAction]);

  const cur = pageForRoute(route);
  const homeState = !loaded ? "loading" : (t.homeState || "Ready").toLowerCase().replace(/[^a-z]/g, "");
  const accentOn = true;

  const trunc = (s, n) => (s.length > n ? s.slice(0, n) + "…" : s);
  let crumbs;
  if (route === "inbox" && currentEmail) {
    crumbs = [{ label: "Email" }, { label: "Inbox triage", to: "inbox" }, { label: trunc(currentEmail.subject, 44) }];
  } else if (route === "drafts" && currentDraft) {
    crumbs = [{ label: "Email" }, { label: "Drafts", to: "drafts" }, { label: trunc(currentDraft.subject || "New message", 44) }];
  } else if (route === "runs" && currentRun) {
    crumbs = [{ label: "Email" }, { label: "Runs", to: "runs" }, { label: currentRun.kind + " #" + currentRun.id }];
  } else {
    crumbs = cur.path.split(" / ").map((p) => ({ label: p }));
  }

  return (
    <div className="app-shell">
      <Sidebar collapsed={collapsed} route={route} onNavigate={navigate} indicator={(t.indicator || "Bar").toLowerCase()} />
      <div className="main-col">
        <TopBar
          collapsed={collapsed}
          onToggle={() => setCollapsed((c) => !c)}
          crumbs={crumbs}
          onCrumb={navigate}
          onOpenPalette={() => setPaletteOpen(true)}
          apiStatus={homeState === "error" ? "down" : "connected"}
        />
        <main className="content" tabIndex={-1}>
          <div className="content-inner" key={route + ":" + (emailId || "") + ":" + (draftId || "") + ":" + (runId || "")}>
            {route === "home" ? (
              <Home
                state={homeState === "error" || homeState === "empty" || homeState === "loading" ? homeState : "ready"}
                layout={(t.homeLayout || "Stats-forward") === "Activity-forward" ? "activity" : "stats"}
                accentOn={accentOn}
                onNavigate={navigate}
                onAction={runAction}
                onRetry={() => { setLoaded(false); setTweak("homeState", "Ready"); setTimeout(() => setLoaded(true), 650); }}
              />
            ) : route === "inbox" && currentEmail ? (
              <EmailDetail email={currentEmail} draft={drafts.find((d) => d.emailId === currentEmail.id)} onStatus={(s) => setStatus(currentEmail.id, s)} onOpenComposer={openComposer} onDiscardDraft={discardDraft} />
            ) : route === "inbox" ? (
              <InboxTriage emails={emails} loading={!loaded} enabled={!paletteOpen} onOpen={openDetail} onBulk={bulkUpdate} />
            ) : route === "drafts" && currentDraft ? (
              <DraftComposer draft={currentDraft} onDiscard={discardDraft} onSent={sendDraft} onSave={saveDraftLocal} onSaveGmail={saveDraftGmail} />
            ) : route === "drafts" ? (
              <DraftsList drafts={drafts} loading={!loaded} enabled={!paletteOpen} lastSent={lastSent} onDismissSent={() => setLastSent(null)} onOpen={openDraft} onDiscard={discardDraft} onNewOutreach={newOutreach} />
            ) : route === "reminders" ? (
              <Reminders reminders={reminders} loading={!loaded} onCancel={cancelReminder} onAdd={addReminder} />
            ) : route === "usage" ? (
              <Observability loading={!loaded} />
            ) : route === "logs" ? (
              <LogsExplorer loading={!loaded} />
            ) : route === "runs" && currentRun ? (
              <RunDetail run={currentRun} runs={runs} now={now} onOpenRun={openRun} onBackList={() => navigate("runs")} />
            ) : route === "runs" ? (
              <RunsList runs={runs} loading={!loaded} now={now} onOpen={openRun} onTrigger={triggerRun} />
            ) : route === "soul" ? (
              <SoulPersona initial={window.ROTOM.SOUL_DOC} onSaved={() => {}} />
            ) : (
              <ComingSoon item={cur} onBack={() => navigate("home")} />
            )}
          </div>
        </main>
      </div>

      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        onNavigate={navigate}
        onAction={runAction}
        onOpenEmail={openEmail}
      />

      <Toaster toasts={toasts} />

      <TweaksPanel title="Tweaks">
        <TweakSection label="Identity" />
        <TweakRadio label="Accent" value={t.accent} options={["Indigo", "Violet", "Blue"]} onChange={(v) => setTweak("accent", v)} />
        <TweakRadio label="Neutral ramp" value={t.tint} options={["Cool tint", "Pure neutral"]} onChange={(v) => setTweak("tint", v)} />
        <TweakSection label="Density" />
        <TweakRadio label="Tables / lists" value={t.density} options={["Compact", "Balanced"]} onChange={(v) => setTweak("density", v)} />
        <TweakSection label="Navigation" />
        <TweakRadio label="Active indicator" value={t.indicator} options={["Bar", "Dot", "Fill"]} onChange={(v) => setTweak("indicator", v)} />
        <TweakSection label="Home layout" />
        <TweakRadio label="Arrangement" value={t.homeLayout} options={["Stats-forward", "Activity-forward"]} onChange={(v) => setTweak("homeLayout", v)} />
        <TweakSelect label="Demo state" value={t.homeState} options={["Ready", "Loading", "Empty", "Error"]} onChange={(v) => { setTweak("homeState", v); if (v === "Loading") { setLoaded(false); setTimeout(() => setLoaded(true), 1200); } }} />
      </TweaksPanel>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
