import { getLogs } from "@/lib/api";
import { LogsExplorer } from "@/components/logs-explorer";

export const dynamic = "force-dynamic";

export default async function LogsPage() {
  // Seed the initial render with the last hour of logs (newest first)
  const since = new Date(Date.now() - 60 * 60 * 1000).toISOString();
  const initialPage = await getLogs({ since, limit: 100 });

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight">Logs Explorer</h2>
        <p className="text-muted-foreground text-sm">
          Structured application logs with faceted search and live-tail
        </p>
      </div>

      <LogsExplorer initialPage={initialPage} />
    </div>
  );
}
