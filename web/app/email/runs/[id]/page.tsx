import { notFound } from "next/navigation";

import { getRun } from "@/lib/api";
import { RunDetailLive } from "@/components/run-detail-live";
import { Panel } from "@/components/ui/panel";
import { EmptyState } from "@/components/ui/empty-state";

export const dynamic = "force-dynamic";

export default async function RunDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  let run;
  try {
    run = await getRun(id);
  } catch (e) {
    if (e instanceof Error && /\bAPI 404\b/.test(e.message)) notFound();
    return (
      <Panel>
        <EmptyState
          icon="TriangleAlert"
          title="Couldn't load this run"
          body={
            e instanceof Error && /fetch failed/i.test(e.message)
              ? "The backend API is unreachable. Start it and refresh."
              : e instanceof Error
                ? e.message
                : "Unknown error reaching the backend."
          }
        />
      </Panel>
    );
  }

  return <RunDetailLive initialRun={run} runId={id} />;
}
