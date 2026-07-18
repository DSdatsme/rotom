import { getReminders } from "@/lib/api";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { ReminderBoard } from "@/components/reminder-board";
import { ReminderChatBar } from "@/components/reminder-chat-bar";

export const dynamic = "force-dynamic";

export default async function RemindersPage() {
  let reminders;
  try {
    reminders = await getReminders("pending");
  } catch (e) {
    return (
      <Alert variant="destructive">
        <AlertTitle>API unreachable</AlertTitle>
        <AlertDescription>{e instanceof Error ? e.message : "unknown error"}</AlertDescription>
      </Alert>
    );
  }

  return (
    <div className="flex min-h-[calc(100vh-6rem)] flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Reminders</h1>
        <p className="text-sm text-muted-foreground">
          Fired to your Telegram chat. Add with the + tile or describe one below.
        </p>
      </div>

      <div className="flex-1">
        {reminders.length === 0 ? (
          <p className="mb-4 text-sm text-muted-foreground">No pending reminders.</p>
        ) : null}
        <ReminderBoard reminders={reminders} />
      </div>

      <ReminderChatBar />
    </div>
  );
}
