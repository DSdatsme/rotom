import type { CalendarEvent } from "@/lib/api";
import { colorForAccount } from "@/lib/calendar-colors";

const HOUR_HEIGHT = 48; // px per hour row
const DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function dateForDayOffset(weekStart: string, offset: number): string {
  const d = new Date(`${weekStart}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + offset);
  return d.toISOString().slice(0, 10);
}

// Read the wall-clock time straight out of the ISO string's own text — never construct a
// Date and call .getHours(), which would reinterpret it in the server's local timezone.
function minutesSinceMidnight(iso: string): number {
  const [h, m] = iso.slice(11, 16).split(":").map(Number);
  return h * 60 + m;
}

export function CalendarGrid({ weekStart, events }: { weekStart: string; events: CalendarEvent[] }) {
  const days = Array.from({ length: 7 }, (_, i) => dateForDayOffset(weekStart, i));

  const timedByDay = new Map<string, CalendarEvent[]>();
  const allDayByDay = new Map<string, CalendarEvent[]>();
  for (const day of days) {
    timedByDay.set(day, []);
    allDayByDay.set(day, []);
  }
  for (const ev of events) {
    const day = ev.start.slice(0, 10);
    const bucket = ev.all_day ? allDayByDay : timedByDay;
    bucket.get(day)?.push(ev);
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <div className="grid grid-cols-[3.5rem_repeat(7,1fr)] border-b border-border">
        <div />
        {days.map((day, i) => (
          <div key={day} className="border-l border-border px-2 py-2 text-center text-sm font-medium">
            {DAY_LABELS[i]} <span className="text-muted-foreground">{day.slice(5)}</span>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-[3.5rem_repeat(7,1fr)] border-b border-border">
        <div className="px-2 py-1 text-right text-xs text-muted-foreground">All day</div>
        {days.map((day) => (
          <div key={day} className="flex flex-col gap-1 border-l border-border p-1">
            {allDayByDay.get(day)!.map((ev) => (
              <span
                key={`${ev.account}-${ev.event_id}`}
                className={`truncate rounded px-1.5 py-0.5 text-xs ${colorForAccount(ev.account)}`}
                title={`${ev.title} (${ev.account})`}
              >
                {ev.title}
              </span>
            ))}
          </div>
        ))}
      </div>

      <div className="grid grid-cols-[3.5rem_repeat(7,1fr)]">
        <div>
          {Array.from({ length: 24 }, (_, h) => (
            <div
              key={h}
              style={{ height: HOUR_HEIGHT }}
              className="border-t border-border px-2 text-right text-xs text-muted-foreground"
            >
              {h === 0 ? "" : `${h}:00`}
            </div>
          ))}
        </div>
        {days.map((day) => (
          <div key={day} className="relative border-l border-border">
            {Array.from({ length: 24 }, (_, h) => (
              <div key={h} style={{ height: HOUR_HEIGHT }} className="border-t border-border" />
            ))}
            {timedByDay.get(day)!.map((ev) => {
              const startMin = minutesSinceMidnight(ev.start);
              let durationMin = minutesSinceMidnight(ev.end) - startMin;
              if (durationMin <= 0) durationMin = 24 * 60 - startMin; // crosses midnight: simplify to day's end
              const top = (startMin / 60) * HOUR_HEIGHT;
              const height = Math.max((durationMin / 60) * HOUR_HEIGHT, 18);
              return (
                <div
                  key={`${ev.account}-${ev.event_id}`}
                  className={`absolute right-0.5 left-0.5 overflow-hidden rounded px-1 text-xs ${colorForAccount(ev.account)}`}
                  style={{ top, height }}
                  title={`${ev.title} (${ev.account})${ev.location ? " · " + ev.location : ""}`}
                >
                  {ev.title}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}
