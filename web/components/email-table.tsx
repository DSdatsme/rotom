"use client";

import { useEffect, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Check, Minus, CircleCheck, CircleSlash, CircleDot, X, Loader } from "lucide-react";

import type { EmailView, Tone } from "@/lib/view/email";
import { setEmailsStatus } from "@/lib/actions";
import { Icon } from "@/components/ui/icon";
import { UrgencyScale } from "@/components/ui/urgency-scale";

/** Mock CSS tone tokens: our "brand" maps to the mock's "accent". */
function toneCls(tone: Tone): string {
  return tone === "brand" ? "accent" : tone;
}

export function EmailTable({ emails }: { emails: EmailView[] }) {
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [cursor, setCursor] = useState(0);
  const [pending, startTransition] = useTransition();
  const router = useRouter();

  const allSelected = emails.length > 0 && selected.size === emails.length;
  const someSelected = selected.size > 0 && !allSelected;

  const toggle = (id: number) =>
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const mark = (status: "done" | "irrelevant" | "open", ids = [...selected]) => {
    if (ids.length === 0) return;
    startTransition(async () => {
      const r = await setEmailsStatus(ids, status);
      if (r.ok) {
        setSelected(new Set());
        router.refresh();
      }
    });
  };

  // j/k move · x select · e done · enter open
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const el = e.target as HTMLElement;
      if (/^(input|textarea|select)$/i.test(el?.tagName ?? "") || el?.isContentEditable) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const k = e.key.toLowerCase();
      if (k === "j") {
        e.preventDefault();
        setCursor((c) => Math.min(c + 1, emails.length - 1));
      } else if (k === "k") {
        e.preventDefault();
        setCursor((c) => Math.max(c - 1, 0));
      } else if (k === "x") {
        e.preventDefault();
        const row = emails[cursor];
        if (row) toggle(row.id);
      } else if (k === "enter") {
        const row = emails[cursor];
        if (row) router.push(`/email/${row.id}`);
      } else if (k === "e") {
        const row = emails[cursor];
        if (row) mark("done", [row.id]);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [emails, cursor]);

  return (
    <div className="tbl-wrap">
      <table className="tbl">
        <colgroup>
          <col style={{ width: "38px" }} />
          <col style={{ width: "140px" }} />
          <col />
          <col style={{ width: "248px" }} />
          <col style={{ width: "158px" }} />
          <col style={{ width: "104px" }} />
          <col style={{ width: "58px" }} />
          <col style={{ width: "82px" }} />
          <col style={{ width: "92px" }} />
        </colgroup>
        <thead>
          <tr>
            <th
              className="col-check"
              onClick={() => setSelected(allSelected ? new Set() : new Set(emails.map((e) => e.id)))}
            >
              <span className={"checkbox" + (allSelected ? " on" : "") + (someSelected ? " some" : "")}>
                {allSelected && <Check size={12} />}
                {someSelected && <Minus size={12} />}
              </span>
            </th>
            <th>Account</th>
            <th>Subject</th>
            <th>From</th>
            <th>Category</th>
            <th>Status</th>
            <th>Urg.</th>
            <th>Email date</th>
            <th>Triaged</th>
          </tr>
        </thead>
        <tbody>
          {emails.map((e, i) => (
            <tr
              key={e.id}
              className={"row" + (selected.has(e.id) ? " selected" : "") + (i === cursor ? " cursor" : "")}
              onMouseEnter={() => setCursor(i)}
            >
              <td
                className="col-check"
                onClick={(ev) => {
                  ev.stopPropagation();
                  toggle(e.id);
                }}
              >
                <span className={"checkbox" + (selected.has(e.id) ? " on" : "")}>
                  {selected.has(e.id) && <Check size={12} />}
                </span>
              </td>
              <td className="col-acct mono">{e.account}</td>
              <td className="col-subj">
                <button className="subj-link" onClick={() => router.push(`/email/${e.id}`)}>
                  {e.subject}
                </button>
              </td>
              <td className="col-from">
                <span className="from-name">{e.senderName}</span>
                <span className="from-addr mono">{e.senderAddr}</span>
              </td>
              <td className="col-cat">
                <span className="cat-cell">
                  <span className={"cat-badge tone-" + toneCls(e.category.tone)}>
                    <Icon name={e.category.icon} size={12} />
                    {e.category.label}
                  </span>
                  {e.suspicious && (
                    <span className="inj-badge" title="Possible prompt injection — handle with care">
                      <Icon name="Shield" size={12} />
                    </span>
                  )}
                </span>
              </td>
              <td className="col-status">
                <span className={"status-badge tone-" + toneCls(e.status.tone)}>
                  <Icon name={e.status.icon} size={12} />
                  {e.status.label}
                </span>
              </td>
              <td className="col-urg">
                <UrgencyScale segments={e.urgency.segments} label={e.urgency.label} />
              </td>
              <td className="col-date mono">
                {e.received.date}
                <span className="date-time">{e.received.time}</span>
              </td>
              <td className="col-triaged mono">{e.triaged}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {selected.size > 0 && (
        <div className="bulk-bar" role="toolbar" aria-label="Bulk actions">
          <span className="bulk-info">
            <span className="mono">{selected.size}</span> selected
          </span>
          <div className="bulk-sep" />
          <button className="bulk-act" disabled={pending} onClick={() => mark("done")}>
            {pending ? <Loader size={14} className="animate-spin" /> : <CircleCheck size={14} />} Mark done
          </button>
          <button className="bulk-act" disabled={pending} onClick={() => mark("irrelevant")}>
            <CircleSlash size={14} /> Mark irrelevant
          </button>
          <button className="bulk-act" disabled={pending} onClick={() => mark("open")}>
            <CircleDot size={14} /> Reopen
          </button>
          <button className="bulk-clear" onClick={() => setSelected(new Set())} aria-label="Clear selection">
            <X size={15} />
          </button>
        </div>
      )}
    </div>
  );
}
