import Link from "next/link";
import { Lock, Send, CircleCheck } from "lucide-react";

import { getDrafts } from "@/lib/api";
import { toDraftView } from "@/lib/view/draft";
import { Panel } from "@/components/ui/panel";
import { EmptyState } from "@/components/ui/empty-state";
import { CategoryBadge } from "@/components/category-badge";
import { DiscardDraftButton } from "@/components/discard-draft-button";
import { CreateDraftButton } from "@/components/create-draft-button";

export const dynamic = "force-dynamic";

/** Mock CSS tone tokens: our "brand" maps to the mock's "accent". */
function toneCls(tone: string): string {
  return tone === "brand" ? "accent" : tone;
}

export default async function DraftsPage({
  searchParams,
}: {
  searchParams: Promise<{ sent?: string }>;
}) {
  const { sent } = await searchParams;
  let drafts;
  try {
    drafts = await getDrafts("pending");
  } catch (e) {
    return (
      <Panel>
        <EmptyState
          icon="TriangleAlert"
          title="API unreachable"
          body={e instanceof Error ? e.message : "unknown error"}
        />
      </Panel>
    );
  }

  const now = Date.now();
  const views = drafts.map((d) => ({ raw: d, v: toDraftView(d, now) }));

  return (
    <div className="drafts">
      <div className="drafts-head">
        <div>
          <h1 className="page-title">Drafts</h1>
          <p className="page-sub">Replies drafted by the agent. Nothing is sent until you say so.</p>
        </div>
        <CreateDraftButton />
      </div>

      {sent && (
        <div className="sent-alert" role="status">
          <CircleCheck size={17} />
          <div className="sent-text">
            <span className="sent-title">Sent via Gmail</span>
            <span className="sent-sub">Delivered and moved out of drafts.</span>
          </div>
        </div>
      )}

      <div className="gate-strip">
        <Lock size={13} />
        <span>
          <span className="gate-strong">{views.length} held</span> — rotom never sends on its own. You stay the gate.
        </span>
      </div>

      {views.length === 0 ? (
        <Panel>
          <EmptyState
            icon="PenLine"
            title="No pending drafts"
            body="When rotom drafts a reply or you start an outreach, it waits here for your review and send."
          />
        </Panel>
      ) : (
        <div className="draft-list">
          {views.map(({ raw: d, v }) => (
            <div key={d.id} className="draft-card">
              <span className={"dc-rail tone-" + toneCls(v.railTone)} />
              <div className="dc-main">
                <div className="dc-top">
                  {v.isOutreach ? (
                    <span className="outreach-pill">
                      <Send size={11} /> Outreach
                    </span>
                  ) : d.email ? (
                    <CategoryBadge category={d.email.category} />
                  ) : null}
                  <span className="dc-kind">{v.kindLabel}</span>
                  <Link href={`/email/drafts/${d.id}`} className="dc-title after:absolute after:inset-0">
                    {v.subject || "New message"}
                  </Link>
                </div>
                <div className="dc-to mono">
                  to {v.recipientName || "…"}
                  {v.recipientEmail && v.recipientEmail !== v.recipientName && (
                    <span className="dc-to-email"> &lt;{v.recipientEmail}&gt;</span>
                  )}
                  {" · "}
                  {v.account || "…"}
                </div>
                <p className="dc-preview">{v.preview}</p>
              </div>
              <div className="dc-side">
                <span className="dc-updated mono">{v.updated}</span>
                <span className="dc-gate">
                  <Lock size={11} /> Held
                </span>
                <DiscardDraftButton draftId={d.id} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
