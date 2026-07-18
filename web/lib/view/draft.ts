import type { DraftItem } from "@/lib/api";
import type { Tone } from "@/lib/view/email";
import { categoryMeta } from "@/lib/view/email";
import { relativeTime } from "@/lib/format/datetime";

/** Collapse newlines/runs of whitespace into a single-line preview. */
export function previewLine(body: string): string {
  return body.replace(/\s+/g, " ").trim();
}

function recipientName(toAddr: string | null): string {
  if (!toAddr) return "";
  const m = /^\s*(.+?)\s*<([^>]+)>\s*$/.exec(toAddr);
  return m ? m[1] : toAddr;
}

/** Bare email address out of a "Name <addr>" or plain-address string. */
function recipientEmail(toAddr: string | null): string {
  if (!toAddr) return "";
  const m = /<([^>]+)>/.exec(toAddr);
  return m ? m[1] : toAddr;
}

export interface DraftView {
  id: number;
  isOutreach: boolean;
  kindLabel: string;
  subject: string;
  recipientName: string;
  recipientEmail: string;
  toAddr: string;
  account: string | null;
  railTone: Tone;
  preview: string;
  updated: string;
  footerDefault: boolean;
}

export function toDraftView(d: DraftItem, now: number = Date.now()): DraftView {
  const isOutreach = d.kind === "outreach";
  const railTone: Tone = isOutreach
    ? "brand"
    : d.email
      ? categoryMeta(d.email.category).tone
      : "muted";
  // Reply drafts leave to_addr/account empty in the DB (null OR "") — the
  // recipient and account are derived from the linked email at send time (see
  // routes.py save_to_gmail). Mirror that fallback here so the list/detail
  // show them. Use `||` (not `??`): empty string also means "not set".
  const toAddr = d.to_addr || d.email?.sender || "";
  const account = d.account || d.email?.account || null;
  return {
    id: d.id,
    isOutreach,
    kindLabel: isOutreach ? "New message" : "Reply",
    subject: d.subject ?? "",
    recipientName: recipientName(toAddr || null),
    recipientEmail: recipientEmail(toAddr || null),
    toAddr,
    account,
    railTone,
    preview: previewLine(d.body),
    updated: relativeTime(d.created_at, now),
    footerDefault: d.rotom_footer_default,
  };
}
