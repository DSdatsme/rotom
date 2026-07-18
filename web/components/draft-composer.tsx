"use client";

import { useState, useTransition, useEffect, useRef } from "react";
import { Sparkles, Mail, Loader, Trash2, Save, Send, Cloud, Check, Paperclip } from "lucide-react";
import {
  discardDraft,
  saveDraft,
  sendDraft,
  sendMessageAction,
  saveToGmailAction,
} from "@/lib/actions";
import type { DraftItem, Attachment } from "@/lib/api";

const preview = (s: string) => s.replace(/\n+/g, " ").trim();

export function DraftComposer({
  draft,
  availableAttachments,
}: {
  draft: DraftItem;
  availableAttachments: Attachment[];
}) {
  const isOutreach = draft.kind === "outreach";

  const [body, setBody] = useState(draft.body);
  const [subject, setSubject] = useState(draft.subject || "");
  const [toAddr, setToAddr] = useState(draft.to_addr || draft.email?.sender || "");
  const [attachments, setAttachments] = useState<string[]>(draft.attachments.map((a) => a.key));
  const [rotomFooter, setRotomFooter] = useState(draft.rotom_footer_default);

  const [chatMessage, setChatMessage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<"local" | "gmail" | null>(null);
  const [pending, startTransition] = useTransition();

  const threadRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (threadRef.current) threadRef.current.scrollTop = threadRef.current.scrollHeight;
  }, [draft.messages, pending]);

  const run = (action: () => Promise<{ ok: boolean; error?: string } | void>, onOk?: () => void) => {
    setError(null);
    startTransition(async () => {
      const result = await action();
      if (result && !result.ok) setError(result.error ?? "Something went wrong");
      else onOk?.();
    });
  };

  const flashSaved = (where: "local" | "gmail") => {
    setSaved(where);
    setTimeout(() => setSaved(null), 2400);
  };

  const handleGenerate = () => {
    if (!chatMessage.trim()) return;
    run(async () => {
      const res = await sendMessageAction(draft.id, chatMessage);
      if (res.ok && res.draft) {
        setBody(res.draft.body);
        setSubject(res.draft.subject || "");
        setToAddr(res.draft.to_addr || toAddr);
        setChatMessage("");
      }
      return res;
    });
  };

  const sendDisabled = pending || !body.trim() || (isOutreach && !toAddr.trim());
  const subjectVal = subject || draft.email?.subject || "";

  return (
    <div className="composer">
      <div className="composer-grid">
        {/* LEFT — chat */}
        <section className="cmp-pane">
          <header className="cmp-head">
            <span className="cmp-head-title">
              <Sparkles size={14} /> Composer chat
            </span>
            <span className="cmp-head-sub">{isOutreach ? "New outreach" : "Reply"}</span>
          </header>

          {draft.kind === "reply" && draft.email && (
            <div className="orig-email">
              <div className="orig-label">Replying to</div>
              <div className="orig-subject">{draft.email.subject}</div>
              <div className="orig-from mono">{draft.email.sender}</div>
              <p className="orig-snip">{preview(draft.email.body || draft.email.snippet)}</p>
            </div>
          )}

          <div className="chat-thread" ref={threadRef}>
            {draft.messages.length === 0 && !pending && (
              <div className="chat-hint">
                Tell rotom what to draft. It collaborates with you here; the letter on the right updates live.
              </div>
            )}
            {draft.messages.map((m, i) => (
              <div key={i} className={"chat-msg " + (m.role === "user" ? "from-user" : "from-rotom")}>
                {m.role !== "user" && (
                  <span className="chat-av">
                    <Sparkles size={13} />
                  </span>
                )}
                <div className="chat-bubble">{m.content}</div>
              </div>
            ))}
            {pending && (
              <div className="chat-msg from-rotom">
                <span className="chat-av">
                  <Sparkles size={13} />
                </span>
                <div className="chat-bubble">
                  <Loader size={14} className="animate-spin" />
                </div>
              </div>
            )}
          </div>

          <div className="chat-input">
            <textarea
              className="chat-textarea"
              placeholder="Tell the agent what to draft… (Shift+Enter for newline)"
              value={chatMessage}
              onChange={(e) => setChatMessage(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleGenerate();
                }
              }}
              rows={2}
              disabled={pending}
            />
            <button className="btn btn-primary btn-sm" onClick={handleGenerate} disabled={pending || !chatMessage.trim()}>
              {pending ? <Loader size={14} className="animate-spin" /> : <Sparkles size={14} />}
              <span>{pending ? "Drafting…" : "Generate"}</span>
            </button>
          </div>
        </section>

        {/* RIGHT — letter */}
        <section className="cmp-pane">
          <header className="cmp-head">
            <span className="cmp-head-title">
              <Mail size={14} /> Draft preview
            </span>
            <span className="cmp-head-sub mono">{draft.account || draft.email?.account || ""}</span>
          </header>

          <div className="letter">
            {error && <div className="cf-saved" style={{ color: "var(--destructive)" }}>{error}</div>}

            <div className="letter-fields">
              {isOutreach ? (
                <>
                  <label className="lf-row">
                    <span className="lf-key">To</span>
                    <input
                      className="lf-input mono"
                      value={toAddr}
                      onChange={(e) => setToAddr(e.target.value)}
                      placeholder="recipient@email.com"
                    />
                  </label>
                  <label className="lf-row">
                    <span className="lf-key">Subject</span>
                    <input
                      className="lf-input"
                      value={subject}
                      onChange={(e) => setSubject(e.target.value)}
                      placeholder="Subject line"
                    />
                  </label>
                </>
              ) : (
                <>
                  <div className="lf-row">
                    <span className="lf-key">To</span>
                    <span className="lf-val mono">{toAddr}</span>
                  </div>
                  <div className="lf-row">
                    <span className="lf-key">Subject</span>
                    <span className="lf-val">{subjectVal}</span>
                  </div>
                </>
              )}
            </div>

            <textarea
              className="letter-body"
              value={body}
              onChange={(e) => setBody(e.target.value)}
              placeholder="Your message…"
              disabled={pending}
            />

            {availableAttachments.length > 0 && (
              <div className="attach">
                <div className="attach-label">
                  <Paperclip size={12} /> Attachments
                </div>
                {availableAttachments.map((a) => {
                  const on = attachments.includes(a.key);
                  return (
                    <label key={a.key} className="attach-row">
                      <span
                        className={"checkbox" + (on ? " on" : "")}
                        onClick={(e) => {
                          e.preventDefault();
                          setAttachments((prev) => (on ? prev.filter((k) => k !== a.key) : [...prev, a.key]));
                        }}
                      >
                        {on && <Check size={11} />}
                      </span>
                      <span className="attach-name">{a.label}</span>
                    </label>
                  );
                })}
              </div>
            )}

            {rotomFooter && <div className="letter-footer">— Sent with rotom</div>}
          </div>
        </section>
      </div>

      {/* FOOTER — commit bar */}
      <div className="composer-footer">
        <button className="btn btn-ghost btn-sm cf-discard" disabled={pending} onClick={() => run(() => discardDraft(draft.id))}>
          <Trash2 size={14} />
          <span>Discard</span>
        </button>

        <div className="cf-right">
          {saved && (
            <span className="cf-saved">
              <Check size={13} /> Saved to {saved === "local" ? "this device" : "Gmail"}
            </span>
          )}

          <button
            className={"footer-toggle" + (rotomFooter ? " on" : "")}
            onClick={() => setRotomFooter((v) => !v)}
            aria-pressed={rotomFooter}
            title="Append a “Sent with rotom” signature line to the bottom of this email."
          >
            <span className="ft-switch">
              <span className="ft-knob" />
            </span>
            <span className="ft-label">rotom footer</span>
          </button>

          <div className="cf-sep" />

          <button
            className="btn btn-default btn-sm"
            data-rotom-wink
            disabled={pending}
            title="Save a local copy — does not touch Gmail."
            onClick={() => run(() => saveDraft(draft.id, { body, subject, to_addr: toAddr, attachments }), () => flashSaved("local"))}
          >
            <Save size={14} />
            <span>Save</span>
          </button>
          <button
            className="btn btn-default btn-sm"
            data-rotom-wink
            disabled={pending}
            title="Save into your Gmail drafts folder — still not sent."
            onClick={() =>
              run(
                () => saveToGmailAction(draft.id, { body, subject, to_addr: toAddr, attachments }, rotomFooter),
                () => flashSaved("gmail"),
              )
            }
          >
            <Cloud size={14} />
            <span>Save to Gmail</span>
          </button>
          <button
            className="btn btn-primary btn-md cf-send"
            data-rotom-wink
            disabled={sendDisabled}
            title="Actually send this email now."
            onClick={() => run(() => sendDraft(draft.id, { body, subject, to_addr: toAddr, attachments }, rotomFooter))}
          >
            {pending ? <Loader size={15} className="animate-spin" /> : <Send size={15} />}
            <span>{pending ? "Sending…" : "Send"}</span>
          </button>
        </div>
      </div>
    </div>
  );
}
