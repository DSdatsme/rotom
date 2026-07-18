"use client";

import { useEffect, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { AlarmClock, Loader2, Plus, Repeat, X } from "lucide-react";

import { cancelReminderAction, createReminderAction } from "@/lib/actions";
import type { ReminderItem } from "@/lib/api";
import { reminderUrgency } from "@/lib/view/reminder";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

function formatCountdown(ms: number): string {
  if (ms <= 0) return "due now";
  const s = Math.floor(ms / 1000);
  const days = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const hms = `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
  return days > 0 ? `${days}d ${hms}` : hms;
}

function ReminderTile({ reminder, now }: { reminder: ReminderItem; now: number | null }) {
  const [pending, startTransition] = useTransition();
  const router = useRouter();
  const target = reminder.next_fire_at ? new Date(reminder.next_fire_at).getTime() : null;
  const remaining = now !== null && target !== null ? target - now : null;

  // When a timer hits zero, pull fresh data once so fired reminders drop off.
  const due = remaining !== null && remaining <= 0;
  useEffect(() => {
    if (!due) return;
    const t = setTimeout(() => router.refresh(), 3000);
    return () => clearTimeout(t);
  }, [due, router]);

  const urgency = reminderUrgency(remaining);

  return (
    <Card
      className={cn(
        "relative",
        urgency === "due" && "border-destructive/40",
        urgency === "soon" && "border-warning/40",
      )}
    >
      <CardHeader className="flex flex-row items-start justify-between gap-2 pb-2">
        <CardTitle className="text-sm font-medium leading-snug">{reminder.text}</CardTitle>
        <Button
          variant="ghost"
          size="icon"
          disabled={pending}
          className="-mr-2 -mt-2 h-7 w-7 shrink-0 text-muted-foreground hover:text-destructive"
          aria-label="Cancel reminder"
          onClick={() =>
            startTransition(async () => {
              const r = await cancelReminderAction(reminder.id);
              if (r.ok) router.refresh();
            })
          }
        >
          {pending ? <Loader2 className="animate-spin" /> : <X />}
        </Button>
      </CardHeader>
      <CardContent className="space-y-1.5">
        <p
          className={cn(
            "font-mono text-2xl tabular-nums tracking-tight",
            urgency === "due" && "text-destructive",
            urgency === "soon" && "text-warning",
          )}
        >
          {remaining === null ? "—" : formatCountdown(remaining)}
        </p>
        <p className="text-xs text-muted-foreground">
          {target !== null
            ? new Date(target).toLocaleString(undefined, {
                weekday: "short",
                month: "short",
                day: "numeric",
                hour: "2-digit",
                minute: "2-digit",
              })
            : "no schedule"}
        </p>
        {reminder.recurrence_cron ? (
          <Badge variant="outline" className="gap-1 font-mono text-[10px]">
            <Repeat className="h-3 w-3" /> {reminder.recurrence_cron}
          </Badge>
        ) : null}
      </CardContent>
    </Card>
  );
}

function AddReminderTile() {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [when, setWhen] = useState("");
  const [cron, setCron] = useState("");
  const [error, setError] = useState("");
  const [pending, startTransition] = useTransition();
  const router = useRouter();

  const submit = () =>
    startTransition(async () => {
      setError("");
      if (!text.trim() || !when) {
        setError("Text and time are required");
        return;
      }
      // datetime-local is naive local time; toISOString() converts to UTC with offset.
      const fireAt = new Date(when).toISOString();
      const r = await createReminderAction(text, fireAt, cron.trim());
      if (!r.ok) {
        setError(r.error ?? "failed");
        return;
      }
      setText("");
      setWhen("");
      setCron("");
      setOpen(false);
      router.refresh();
    });

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="flex min-h-36 items-center justify-center rounded-xl border border-dashed text-muted-foreground transition-colors hover:bg-accent/50 hover:text-foreground"
        aria-label="Add reminder"
      >
        <Plus className="h-8 w-8" />
      </button>
    );
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm font-medium">
          <AlarmClock className="h-4 w-4" /> New reminder
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <Input
          placeholder="What should I remind you about?"
          value={text}
          onChange={(e) => setText(e.target.value)}
          autoFocus
        />
        <Input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} />
        <Input
          placeholder='Repeats? "everyday", "weekdays", "every monday", or cron'
          value={cron}
          onChange={(e) => setCron(e.target.value)}
          className="text-xs"
        />
        {error ? <p className="text-xs text-destructive">{error}</p> : null}
        <div className="flex gap-2">
          <Button size="sm" onClick={submit} disabled={pending}>
            {pending ? <Loader2 className="animate-spin" /> : null} Add
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setOpen(false)} disabled={pending}>
            Cancel
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

export function ReminderBoard({ reminders }: { reminders: ReminderItem[] }) {
  // Tick once a second; null until mounted so SSR/client markup match.
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    setNow(Date.now());
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      {reminders.map((r) => (
        <ReminderTile key={r.id} reminder={r} now={now} />
      ))}
      <AddReminderTile />
    </div>
  );
}
