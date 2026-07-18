const pad = (n: number) => String(n).padStart(2, "0");

/** "2m ago" / "3h ago" / "2d ago"; "—" for null. */
export function relativeTime(iso: string | null, now: number = Date.now()): string {
  if (!iso) return "—";
  const sec = Math.max(0, Math.floor((now - Date.parse(iso)) / 1000));
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return `${Math.floor(sec / 86400)}d ago`;
}

/** Live countdown: "1d 02:03:04" / "00:05:09" / "due now" / "—". */
export function formatCountdown(ms: number | null): string {
  if (ms == null) return "—";
  if (ms <= 0) return "due now";
  const s = Math.floor(ms / 1000);
  const d = Math.floor(s / 86400);
  const h = Math.floor(s / 3600) % 24;
  const m = Math.floor(s / 60) % 60;
  const sec = s % 60;
  return (d > 0 ? `${d}d ` : "") + `${pad(h)}:${pad(m)}:${pad(sec)}`;
}

/** Absolute fire time: "Today 14:30" / "Tomorrow 09:00" / "Jun 16 09:00". */
export function formatFireTime(iso: string | null, now: number = Date.now()): string {
  if (!iso) return "No time set";
  const d = new Date(iso);
  const ref = new Date(now);
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  const tmr = new Date(ref);
  tmr.setDate(ref.getDate() + 1);
  if (d.toDateString() === ref.toDateString()) return `Today ${hm}`;
  if (d.toDateString() === tmr.toDateString()) return `Tomorrow ${hm}`;
  return `${d.toLocaleDateString("en-US", { month: "short", day: "numeric" })} ${hm}`;
}

/** Run duration: "420ms" / "3.21s" / "1m 5s" / "—". */
export function formatDuration(ms: number | null): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(2)}s`;
  return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
}

/** Email date split: { date: "Jun 14", time: "08:21" }. */
export function formatEmailDate(iso: string | null): { date: string; time: string } {
  if (!iso) return { date: "—", time: "" };
  const d = new Date(iso);
  const date = d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  const time = d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false });
  return { date, time };
}
