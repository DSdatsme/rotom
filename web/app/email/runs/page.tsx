import { getRuns } from "@/lib/api";
import { RunsList } from "@/components/runs-list";

export const dynamic = "force-dynamic";

export default async function RunsPage({
  searchParams,
}: {
  searchParams: Promise<{ kind?: string }>;
}) {
  const { kind } = await searchParams;
  const runs = await getRuns(50, { kind: kind || undefined });

  return <RunsList initialRuns={runs} kind={kind || ""} />;
}
