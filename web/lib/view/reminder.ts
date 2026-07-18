import type { ReminderItem } from "@/lib/api";
import { formatFireTime } from "@/lib/format/datetime";

export function reminderUrgency(msToFire: number | null): "none" | "ok" | "soon" | "due" {
  if (msToFire == null) return "none";
  if (msToFire <= 0) return "due";
  if (msToFire < 60 * 60 * 1000) return "soon";
  return "ok";
}

export interface ReminderView {
  id: number;
  text: string;
  msToFire: number | null;
  urgency: "none" | "ok" | "soon" | "due";
  fireLabel: string;
  isRecurring: boolean;
  recurrenceCron: string;
}

export function toReminderView(r: ReminderItem, now: number = Date.now()): ReminderView {
  const fireIso = r.next_fire_at ?? r.fire_at;
  const msToFire = fireIso ? Date.parse(fireIso) - now : null;
  return {
    id: r.id,
    text: r.text,
    msToFire,
    urgency: reminderUrgency(msToFire),
    fireLabel: formatFireTime(fireIso, now),
    isRecurring: Boolean(r.recurrence_cron),
    recurrenceCron: r.recurrence_cron,
  };
}
