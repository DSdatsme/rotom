import type { EmailItem } from "@/lib/api";
import { formatEmailDate, relativeTime } from "@/lib/format/datetime";

export type Tone = "danger" | "warning" | "success" | "brand" | "slate" | "muted";

const URGENCY: Record<number, "none" | "low" | "medium" | "high"> = {
  0: "none",
  1: "low",
  2: "medium",
  3: "high",
};

export function urgencyLabel(n: number): "none" | "low" | "medium" | "high" {
  return URGENCY[n] ?? "none";
}
export function urgencySegments(n: number): number {
  return Math.max(0, Math.min(3, n));
}

const CATEGORY: Record<EmailItem["category"], { tone: Tone; label: string; icon: string }> = {
  critical: { tone: "danger", label: "Critical", icon: "TriangleAlert" },
  needs_reply: { tone: "brand", label: "Needs reply", icon: "CornerDownLeft" },
  fyi: { tone: "slate", label: "FYI", icon: "Info" },
  skip: { tone: "muted", label: "Skip", icon: "Minus" },
};
export function categoryMeta(c: EmailItem["category"]) {
  return CATEGORY[c];
}

const STATUS: Record<EmailItem["status"], { tone: Tone; label: string; icon: string }> = {
  open: { tone: "brand", label: "Open", icon: "CircleDot" },
  done: { tone: "success", label: "Done", icon: "CircleCheck" },
  irrelevant: { tone: "muted", label: "Irrelevant", icon: "CircleSlash" },
};
export function statusMeta(s: EmailItem["status"]) {
  return STATUS[s];
}

export interface EmailView {
  id: number;
  account: string;
  subject: string;
  senderName: string;
  senderAddr: string;
  category: { tone: Tone; label: string; icon: string };
  status: { tone: Tone; label: string; icon: string };
  urgency: { label: string; segments: number };
  suspicious: boolean;
  reason: string;
  received: { date: string; time: string };
  triaged: string;
}

/** Parse "Name <addr>" → {name, addr}; fall back to raw on both. */
export function parseSender(sender: string): { name: string; addr: string } {
  const m = /^\s*(.+?)\s*<([^>]+)>\s*$/.exec(sender);
  if (m) return { name: m[1], addr: m[2] };
  return { name: sender, addr: sender };
}

export function toEmailView(e: EmailItem, now: number = Date.now()): EmailView {
  const { name, addr } = parseSender(e.sender);
  return {
    id: e.id,
    account: e.account,
    subject: e.subject,
    senderName: name,
    senderAddr: addr,
    category: categoryMeta(e.category),
    status: statusMeta(e.status),
    urgency: { label: urgencyLabel(e.urgency), segments: urgencySegments(e.urgency) },
    suspicious: e.suspicious,
    reason: e.reason,
    received: formatEmailDate(e.received_at),
    triaged: relativeTime(e.created_at, now),
  };
}
