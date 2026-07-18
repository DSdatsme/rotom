// Drafts list + Draft composer. Exported to window.
const { useState: useStateD, useEffect: useEffectD, useRef: useRefD } = React;

const preview2 = (s) => s.replace(/\n+/g, " ").trim();

/* ============================================================ DRAFTS LIST */
function DraftCard({ d, cursor, onOpen, onDiscard, onCursor, idx }) {
  const isReply = d.type === "reply";
  return (
    <div
      className={"draft-card" + (cursor ? " cursor" : "")}
      role="button" tabIndex={0}
      onClick={() => onOpen(d.id)}
      onMouseEnter={() => onCursor(idx)}
      onKeyDown={(e) => { if (e.key === "Enter") onOpen(d.id); }}
    >
      <span className={"dc-rail " + (isReply ? "tone-" + (window.ROTOM.CAT[d.cat] || {}).token : "tone-accent")} />
      <div className="dc-main">
        <div className="dc-top">
          {isReply ? <CategoryBadge cat={d.cat} /> : (
            <span className="outreach-pill"><Icon name="send" size={11} />Outreach</span>
          )}
          <span className="dc-kind">{isReply ? "Reply" : "New message"}</span>
          <span className="dc-title">{d.subject}</span>
        </div>
        <div className="dc-to mono">to {d.recipientName} &lt;{d.to}&gt; · {d.account}</div>
        <p className="dc-preview">{preview2(d.body)}</p>
      </div>
      <div className="dc-side">
        <span className="dc-updated mono">{d.updated}</span>
        <span className="dc-gate"><Icon name="lock" size={11} />Held</span>
        <button className="dc-discard" title="Discard draft" onClick={(e) => { e.stopPropagation(); onDiscard(d.id); }}>
          <Icon name="trash" size={15} />
        </button>
      </div>
    </div>
  );
}

function DraftCardSkeleton() {
  return (
    <div className="draft-card skel">
      <span className="dc-rail tone-muted" />
      <div className="dc-main">
        <div className="dc-top"><Skeleton w="72px" h={18} r={9} /><Skeleton w="44%" h={13} /></div>
        <Skeleton w="38%" h={11} style={{ marginTop: 8 }} />
        <Skeleton w="80%" h={11} style={{ marginTop: 9 }} />
      </div>
    </div>
  );
}

function DraftsList({ drafts, loading, enabled, lastSent, onDismissSent, onOpen, onDiscard, onNewOutreach }) {
  const [cursor, setCursor] = useStateD(0);
  useEffectD(() => { setCursor((c) => Math.min(c, Math.max(0, drafts.length - 1))); }, [drafts.length]);

  useEffectD(() => {
    if (!enabled) return;
    function onKey(e) {
      const typing = /^(input|textarea|select)$/i.test((e.target.tagName || "")) || e.target.isContentEditable;
      if (typing || e.metaKey || e.ctrlKey) return;
      const k = e.key.toLowerCase();
      if (k === "j") { e.preventDefault(); setCursor((c) => Math.min(c + 1, drafts.length - 1)); }
      else if (k === "k") { e.preventDefault(); setCursor((c) => Math.max(c - 1, 0)); }
      else if (k === "enter") { const d = drafts[cursor]; if (d) onOpen(d.id); }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [enabled, drafts, cursor]);

  return (
    <div className="drafts">
      <div className="drafts-head">
        <div>
          <h1 className="page-title">Drafts</h1>
          <p className="page-sub">Replies drafted by the agent. Nothing is sent until you say so.</p>
        </div>
        <Button variant="default" size="md" icon="plus" onClick={onNewOutreach}>New outreach</Button>
      </div>

      {lastSent && (
        <div className="sent-alert" role="status">
          <Icon name="circle-check" size={17} />
          <div className="sent-text">
            <span className="sent-title">Sent — “{lastSent}”</span>
            <span className="sent-sub">Delivered and moved out of drafts.</span>
          </div>
          <button className="sent-dismiss" onClick={onDismissSent} aria-label="Dismiss"><Icon name="x" size={15} /></button>
        </div>
      )}

      <div className="gate-strip">
        <Icon name="lock" size={13} />
        <span><span className="gate-strong">{drafts.length} held</span> — rotom never sends on its own. You stay the gate.</span>
      </div>

      {loading ? (
        <div className="draft-list">{[0, 1, 2, 3].map((i) => <DraftCardSkeleton key={i} />)}</div>
      ) : drafts.length === 0 ? (
        <Panel>
          <EmptyState icon="file-text" title="No pending drafts"
            body="When rotom drafts a reply or you start an outreach, it waits here for your review and send."
            action={<Button size="sm" icon="plus" onClick={onNewOutreach}>New outreach</Button>} />
        </Panel>
      ) : (
        <div className="draft-list">
          {drafts.map((d, i) => (
            <DraftCard key={d.id} d={d} idx={i} cursor={i === cursor} onOpen={onOpen} onDiscard={onDiscard} onCursor={setCursor} />
          ))}
        </div>
      )}
    </div>
  );
}

/* ============================================================ COMPOSER */
const ROTOM_REPLIES = [
  "Updated the draft — tightened the opening and kept the ask clear. Take a look on the right.",
  "Done. I made it a touch warmer and more concise. Anything else you'd like to change?",
  "Revised — I led with the decision and moved the context below. Let me know if the tone fits.",
];

function ChatBubble({ m }) {
  const rotom = m.role === "rotom";
  return (
    <div className={"chat-msg " + (rotom ? "from-rotom" : "from-user")}>
      {rotom && <span className="chat-av"><Icon name="sparkles" size={13} /></span>}
      <div className="chat-bubble">{m.text}</div>
    </div>
  );
}

function DraftComposer({ draft, onDiscard, onSent, onSave, onSaveGmail }) {
  const isOutreach = draft.type === "outreach";
  const original = draft.emailId ? window.ROTOM.EMAILS.find((e) => e.id === draft.emailId) : null;

  const [body, setBody] = useStateD(draft.body || "");
  const [to, setTo] = useStateD(draft.to || "");
  const [subject, setSubject] = useStateD(draft.subject || "");
  const [chat, setChat] = useStateD(draft.chat || []);
  const [input, setInput] = useStateD("");
  const [generating, setGenerating] = useStateD(false);
  const [sending, setSending] = useStateD(false);
  const [footerOn, setFooterOn] = useStateD(!!draft.footer);
  const [attachments, setAttachments] = useStateD(draft.attachments || []);
  const [saved, setSaved] = useStateD(null); // {where}
  const genIdx = useRefD(0);
  const threadRef = useRefD(null);

  useEffectD(() => {
    if (threadRef.current) threadRef.current.scrollTop = threadRef.current.scrollHeight;
  }, [chat, generating]);

  const sendDisabled = sending || generating || !body.trim() || (isOutreach && !to.trim());

  function generate() {
    const text = input.trim();
    if (!text || generating) return;
    setChat((c) => [...c, { role: "user", text }]);
    setInput("");
    setGenerating(true);
    setTimeout(() => {
      const reply = ROTOM_REPLIES[genIdx.current % ROTOM_REPLIES.length];
      genIdx.current += 1;
      setChat((c) => [...c, { role: "rotom", text: reply }]);
      // reflect a draft change with zero layout shift
      setBody((b) => b.trim() ? b : "Hi,\n\nThanks for reaching out — here's a first pass at a reply. Happy to adjust.\n\nBest");
      setGenerating(false);
    }, 1150);
  }

  function flashSaved(where) {
    setSaved({ where });
    setTimeout(() => setSaved(null), 2400);
    if (where === "local") onSave(); else onSaveGmail();
  }

  function send() {
    if (sendDisabled) return;
    setSending(true);
    setTimeout(() => { onSent(draft); }, 950);
  }

  return (
    <div className="composer">
      <div className="composer-grid">
        {/* LEFT — chat */}
        <section className="cmp-pane cmp-chat">
          <header className="cmp-head">
            <span className="cmp-head-title"><Icon name="sparkles" size={14} />Composer chat</span>
            <span className="cmp-head-sub">{isOutreach ? "New outreach" : "Reply"}</span>
          </header>

          {original && (
            <div className="orig-email">
              <div className="orig-label">Replying to</div>
              <div className="orig-subject">{original.subject}</div>
              <div className="orig-from mono">{original.fromName} &lt;{original.from}&gt;</div>
              <p className="orig-snip">{preview2(original.body).slice(0, 150)}…</p>
            </div>
          )}

          <div className="chat-thread" ref={threadRef}>
            {chat.length === 0 && !generating && (
              <div className="chat-hint">Tell rotom what to draft. It collaborates with you here; the letter on the right updates live.</div>
            )}
            {chat.map((m, i) => <ChatBubble key={i} m={m} />)}
            {generating && (
              <div className="chat-msg from-rotom">
                <span className="chat-av"><Icon name="sparkles" size={13} /></span>
                <div className="chat-bubble typing"><span></span><span></span><span></span></div>
              </div>
            )}
          </div>

          <div className="chat-input">
            <textarea
              className="chat-textarea"
              placeholder="Tell the agent what to draft… (Shift+Enter for newline)"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); generate(); } }}
              rows={2}
            />
            <Button variant="primary" size="sm" icon={generating ? "loader" : "sparkles"} onClick={generate} disabled={generating || !input.trim()}>
              {generating ? "Drafting…" : "Generate"}
            </Button>
          </div>
        </section>

        {/* RIGHT — letter */}
        <section className="cmp-pane cmp-preview">
          <header className="cmp-head">
            <span className="cmp-head-title"><Icon name="mail" size={14} />Draft preview</span>
            <span className="cmp-head-sub mono">{draft.account}</span>
          </header>

          <div className="letter">
            <div className="letter-fields">
              {isOutreach ? (
                <React.Fragment>
                  <label className="lf-row"><span className="lf-key">To</span>
                    <input className="lf-input mono" value={to} onChange={(e) => setTo(e.target.value)} placeholder="recipient@email.com" />
                  </label>
                  <label className="lf-row"><span className="lf-key">Subject</span>
                    <input className="lf-input" value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="Subject line" />
                  </label>
                </React.Fragment>
              ) : (
                <React.Fragment>
                  <div className="lf-row"><span className="lf-key">To</span><span className="lf-val mono">{to}</span></div>
                  <div className="lf-row"><span className="lf-key">Subject</span><span className="lf-val">{subject}</span></div>
                </React.Fragment>
              )}
            </div>
            <textarea className="letter-body" value={body} onChange={(e) => setBody(e.target.value)} placeholder="Your message…" />
            {attachments.length > 0 && (
              <div className="attach">
                <div className="attach-label"><Icon name="paperclip" size={12} />Attachments</div>
                {attachments.map((a, i) => (
                  <label key={i} className="attach-row">
                    <span className={"checkbox" + (a.checked ? " on" : "")} onClick={(e) => { e.preventDefault(); setAttachments((xs) => xs.map((x, j) => j === i ? { ...x, checked: !x.checked } : x)); }}>
                      {a.checked && <Icon name="check" size={11} />}
                    </span>
                    <span className="attach-name">{a.label}</span>
                  </label>
                ))}
              </div>
            )}
            {footerOn && <div className="letter-footer">— Sent with rotom</div>}
          </div>
        </section>
      </div>

      {/* FOOTER — commit bar */}
      <div className="composer-footer">
        <button className="btn btn-ghost btn-sm cf-discard" onClick={() => onDiscard(draft.id)}><Icon name="trash" size={14} /><span>Discard</span></button>

        <div className="cf-right">
          {saved && <span className="cf-saved"><Icon name="check" size={13} />Saved to {saved.where === "local" ? "this device" : "Gmail"}</span>}

          <button className={"footer-toggle" + (footerOn ? " on" : "")} onClick={() => setFooterOn((v) => !v)} title="Append a “Sent with rotom” signature line to the bottom of this email." aria-pressed={footerOn}>
            <span className="ft-switch"><span className="ft-knob" /></span>
            <span className="ft-label">rotom footer</span>
          </button>

          <div className="cf-sep" />

          <button className="btn btn-default btn-sm" onClick={() => flashSaved("local")} title="Save a local copy — does not touch Gmail."><Icon name="save" size={14} /><span>Save</span></button>
          <button className="btn btn-default btn-sm" onClick={() => flashSaved("gmail")} title="Save into your Gmail drafts folder — still not sent."><Icon name="cloud" size={14} /><span>Save to Gmail</span></button>
          <button className={"btn btn-primary btn-md cf-send" + (sending ? " sending" : "")} onClick={send} disabled={sendDisabled} title="Actually send this email now.">
            <Icon name={sending ? "loader" : "send"} size={15} />
            <span>{sending ? "Sending…" : "Send"}</span>
          </button>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { DraftsList, DraftComposer });
