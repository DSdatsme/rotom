import { notFound } from "next/navigation";

import { getDraft, fetchAttachments } from "@/lib/api";
import { DraftComposer } from "@/components/draft-composer";
import { Panel } from "@/components/ui/panel";
import { EmptyState } from "@/components/ui/empty-state";

export const dynamic = "force-dynamic";

export default async function DraftDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  let draft;
  try {
    draft = await getDraft(Number(id));
  } catch (e) {
    // A real 404 from the API → the draft genuinely doesn't exist.
    if (e instanceof Error && /\bAPI 404\b/.test(e.message)) notFound();
    // Anything else (API unreachable, 5xx, …) is NOT "not found" — say so plainly.
    return (
      <Panel>
        <EmptyState
          icon="TriangleAlert"
          title="Couldn't load this draft"
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

  // Attachments are optional context — never let them block the draft.
  const attachments = await fetchAttachments().catch(() => []);

  return <DraftComposer draft={draft} availableAttachments={attachments} />;
}
