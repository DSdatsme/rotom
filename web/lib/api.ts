import "server-only";

// Server-side API client — the bearer token never reaches the browser.

const API_URL = process.env.API_URL ?? "http://localhost:8000";
const API_TOKEN = process.env.API_TOKEN ?? "";

export interface EmailItem {
  id: number;
  account: string;
  sender: string;
  subject: string;
  snippet: string;
  body?: string;
  category: "critical" | "needs_reply" | "fyi" | "skip";
  status: "open" | "done" | "irrelevant";
  suspicious: boolean;
  urgency: number;
  reason: string;
  received_at: string | null;
  created_at: string | null;
}

export interface Attachment {
  key: string;
  label: string;
}

export interface DraftMessage {
  role: string;
  content: string;
  created_at: string | null;
}

export interface DraftItem {
  id: number;
  kind: "reply" | "outreach";
  body: string;
  subject: string | null;
  to_addr: string | null;
  account: string | null;
  gmail_draft_id: string | null;
  attachments: Attachment[];
  messages: DraftMessage[];
  status: "pending" | "sent" | "discarded";
  created_at: string | null;
  sent_at: string | null;
  rotom_footer_default: boolean;
  email: EmailItem | null;
}

export interface EmailDetail extends EmailItem {
  body: string;
  drafts: { id: number; body: string; status: string; created_at: string | null }[];
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${API_TOKEN}`,
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`API ${res.status} on ${path}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export interface EmailFilters {
  category?: string;
  account?: string;
  status?: string;
  suspicious?: string;
  urgency?: string;
  received_from?: string;
  received_to?: string;
  triaged_from?: string;
  triaged_to?: string;
}

export const getEmails = (filters: EmailFilters = {}) => {
  const params = new URLSearchParams(
    Object.entries(filters).filter(([, v]) => v) as [string, string][],
  );
  const qs = params.toString();
  return apiFetch<EmailItem[]>(`/api/emails${qs ? `?${qs}` : ""}`);
};

export const getAccounts = () => apiFetch<string[]>("/api/emails/accounts");

export const bulkEmailStatus = (ids: number[], status: string) =>
  apiFetch<{ updated: number }>("/api/emails/status", {
    method: "POST",
    body: JSON.stringify({ ids, status }),
  });

export const getDrafts = (status: string = "pending") =>
  apiFetch<DraftItem[]>(`/api/drafts?status=${status}`);

export const getDraft = (id: number) => apiFetch<DraftItem>(`/api/drafts/${id}`);

export const getEmail = (id: number) => apiFetch<EmailDetail>(`/api/emails/${id}`);

export const regenerateEmailDraft = (id: number) =>
  apiFetch<DraftItem>(`/api/emails/${id}/draft`, { method: "POST" });

export const patchDraft = (id: number, update: { body?: string; subject?: string | null; to_addr?: string | null; account?: string | null; attachments?: string[] }) =>
  apiFetch<DraftItem>(`/api/drafts/${id}`, { method: "PATCH", body: JSON.stringify(update) });

export const fetchAttachments = () => apiFetch<Attachment[]>("/api/attachments");

export const createDraft = (kind: "reply" | "outreach") =>
  apiFetch<DraftItem>("/api/drafts", { method: "POST", body: JSON.stringify({ kind }) });

export const postDraftMessage = (id: number, content: string) =>
  apiFetch<DraftItem>(`/api/drafts/${id}/messages`, { method: "POST", body: JSON.stringify({ content }) });

export const saveToGmail = (id: number, rotomFooter?: boolean) =>
  apiFetch<DraftItem>(`/api/drafts/${id}/save-to-gmail`, {
    method: "POST",
    body: JSON.stringify({ rotom_footer: rotomFooter ?? null }),
  });

export const postDraftAction = (id: number, action: "send" | "discard", rotomFooter?: boolean) =>
  apiFetch<DraftItem>(`/api/drafts/${id}/${action}`, {
    method: "POST",
    ...(action === "send" ? { body: JSON.stringify({ rotom_footer: rotomFooter ?? null }) } : {}),
  });

// --- reminders ---

export interface ReminderItem {
  id: number;
  text: string;
  fire_at: string | null;
  next_fire_at: string | null;
  recurrence_cron: string;
  status: "pending" | "fired" | "cancelled";
  created_at: string | null;
  fired_at: string | null;
}

export interface ReminderProposal {
  text: string;
  fire_at: string;
  recurrence_cron: string;
  confirmation: string;
}

export const getReminders = (status: string = "pending") =>
  apiFetch<ReminderItem[]>(`/api/reminders?status=${status}`);

export const createReminder = (text: string, fireAt: string, recurrenceCron: string = "") =>
  apiFetch<ReminderItem>("/api/reminders", {
    method: "POST",
    body: JSON.stringify({ text, fire_at: fireAt, recurrence_cron: recurrenceCron }),
  });

export const parseReminder = (message: string) =>
  apiFetch<ReminderProposal>("/api/reminders/parse", {
    method: "POST",
    body: JSON.stringify({ message }),
  });

export const cancelReminder = (id: number) =>
  apiFetch<{ cancelled: boolean }>(`/api/reminders/${id}`, { method: "DELETE" });

export const getSoul = () => apiFetch<{ content: string }>("/api/soul");

export const updateSoul = (content: string) =>
  apiFetch<{ ok: boolean }>("/api/soul", { method: "PUT", body: JSON.stringify({ content }) });

export type RunStatus = 'running' | 'success' | 'failure' | 'degraded' | 'interrupted';

export interface RunRef {
  id: number;
  kind: string;
  source: string;
  status?: RunStatus;
  started_at?: string | null;
}

export interface RunLog {
  id: number;
  kind: string;
  source: string;
  started_at: string;
  finished_at: string | null;
  status: RunStatus;
  summary: string;
  external_url: string | null;
  parent_run_id: number | null;
}

export interface RunDetail extends RunLog {
  error: string;
  logs: string;
  external_id: string | null;
  parent: RunRef | null;
  children: RunRef[];
  metrics: {
    model: string;
    input_tokens: number;
    output_tokens: number;
    avg_latency_ms: number | null;
  }[];
}

export interface UsageAggregation {
  day: string;
  run_id: number | null;
  purpose: string | null;
  model: string;
  input_tokens: number;
  output_tokens: number;
  avg_latency_ms: number | null;
}

export interface LogEntry {
  id: number;
  ts: string | null;
  level: string;
  logger: string;
  msg: string;
  run_id: number | null;
  kind: string | null;
  extra: string;
}

export interface LogsPage {
  logs: LogEntry[];
  next_before_id: number | null;
}

export interface LogsFilters {
  level?: string;
  kind?: string;
  run_id?: number;
  q?: string;
  since?: string;
  until?: string;
  limit?: number;
  before_id?: number;
}

export const getRuns = (limit = 50, opts: { source?: string; kind?: string } = {}) => {
  const p = new URLSearchParams({ limit: String(limit) });
  if (opts.source) p.set("source", opts.source);
  if (opts.kind) p.set("kind", opts.kind);
  return apiFetch<RunLog[]>(`/api/observability/runs?${p.toString()}`);
};

export const getRun = (id: string) =>
  apiFetch<RunDetail>(`/api/observability/runs/${id}`);

export const getUsage = (days = 14) =>
  apiFetch<UsageAggregation[]>(`/api/observability/usage?days=${days}`);

export const getLogs = (filters: LogsFilters = {}) => {
  const params = new URLSearchParams();
  if (filters.level) params.set("level", filters.level);
  if (filters.kind) params.set("kind", filters.kind);
  if (filters.run_id != null) params.set("run_id", String(filters.run_id));
  if (filters.q) params.set("q", filters.q);
  if (filters.since) params.set("since", filters.since);
  if (filters.until) params.set("until", filters.until);
  if (filters.limit != null) params.set("limit", String(filters.limit));
  if (filters.before_id != null) params.set("before_id", String(filters.before_id));
  const qs = params.toString();
  return apiFetch<LogsPage>(`/api/observability/logs${qs ? `?${qs}` : ""}`);
};

export const triggerRun = () =>
  apiFetch<{ ok: boolean }>("/api/triage/trigger", { method: "POST" });
