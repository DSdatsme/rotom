import { getRuns } from "@/lib/api";
import { RunsList } from "@/components/runs-list";

export const dynamic = "force-dynamic";

export default async function RunsPage() {
  const runs = await getRuns(50);

  return <RunsList initialRuns={runs} />;
}
