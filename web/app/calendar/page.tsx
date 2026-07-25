import Link from "next/link";

import { getCalendarEvents } from "@/lib/api";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { CalendarGrid } from "@/components/calendar-grid";

export const dynamic = "force-dynamic";

function addDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

export default async function CalendarPage({
  searchParams,
}: {
  searchParams: Promise<{ start?: string }>;
}) {
  const { start } = await searchParams;
  let data;
  try {
    data = await getCalendarEvents(start);
  } catch (e) {
    return (
      <Alert variant="destructive">
        <AlertTitle>API unreachable</AlertTitle>
        <AlertDescription>{e instanceof Error ? e.message : "unknown error"}</AlertDescription>
      </Alert>
    );
  }

  const { range_start, range_end, accounts, events, errors } = data;
  const prevStart = addDays(range_start, -7);
  const nextStart = addDays(range_start, 7);

  return (
    <div className="flex min-h-[calc(100vh-6rem)] flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Calendar</h1>
          <p className="text-sm text-muted-foreground">
            {range_start} – {range_end} · merged across all accounts
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" nativeButton={false} render={<Link href={`/calendar?start=${prevStart}`} />}>
            ← Prev
          </Button>
          <Button variant="outline" size="sm" nativeButton={false} render={<Link href="/calendar" />}>
            Today
          </Button>
          <Button variant="outline" size="sm" nativeButton={false} render={<Link href={`/calendar?start=${nextStart}`} />}>
            Next →
          </Button>
        </div>
      </div>

      <CalendarGrid weekStart={range_start} events={events} accounts={accounts} errors={errors} />
    </div>
  );
}
