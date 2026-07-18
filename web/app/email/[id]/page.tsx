import Link from "next/link";
import { notFound } from "next/navigation";
import { PenLine, Sparkles, Shield } from "lucide-react";

import { getEmail } from "@/lib/api";
import { toEmailView } from "@/lib/view/email";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import { EmptyState } from "@/components/ui/empty-state";
import { ToneBadge } from "@/components/ui/tone-badge";
import { UrgencyScale } from "@/components/ui/urgency-scale";
import { DiscardDraftButton } from "@/components/discard-draft-button";
import { EmailStatusButtons } from "@/components/email-status-buttons";
import { RegenerateDraftButton } from "@/components/regenerate-draft-button";

export const dynamic = "force-dynamic";

export default async function EmailDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  let email;
  try {
    email = await getEmail(Number(id));
  } catch {
    notFound();
  }

  const v = toEmailView(email);
  const pendingDraft = email.drafts.find((d) => d.status === "pending");

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <div className="space-y-3">
        <h1 className="text-2xl font-semibold tracking-tight">{email.subject}</h1>
        <p className="text-sm text-muted-foreground">
          from <span className="text-fg-2">{v.senderName}</span>{" "}
          <span className="mono">&lt;{v.senderAddr}&gt;</span>
          <span className="mx-1.5 text-faint">·</span>
          <span className="mono">{email.account}</span>
          <span className="mx-1.5 text-faint">·</span>
          <span className="mono">
            {v.received.date}, {v.received.time}
          </span>
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <ToneBadge tone={v.category.tone} icon={v.category.icon}>
            {v.category.label}
          </ToneBadge>
          {email.suspicious && (
            <ToneBadge tone="warning" icon="Shield">
              Possible injection
            </ToneBadge>
          )}
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
            Urgency <UrgencyScale segments={v.urgency.segments} label={v.urgency.label} />
            <span className="text-fg-2">{v.urgency.label}</span>
          </span>
          <ToneBadge tone={v.status.tone} icon={v.status.icon}>
            {v.status.label}
          </ToneBadge>
        </div>
        <EmailStatusButtons emailId={email.id} status={email.status} />
      </div>

      {email.reason && (
        <div
          className={
            "flex gap-3 rounded-lg border p-3 " +
            (email.suspicious
              ? "border-warning/30 bg-warning/8"
              : "border-border bg-card")
          }
        >
          <span className={email.suspicious ? "text-warning" : "text-brand"}>
            {email.suspicious ? <Shield className="size-4" /> : <Sparkles className="size-4" />}
          </span>
          <div>
            <p className="text-xs font-medium text-fg-2">
              {email.suspicious ? "Why rotom flagged this as suspicious" : "Why rotom flagged this"}
            </p>
            <p className="mt-0.5 text-sm text-muted-foreground">{email.reason}</p>
          </div>
        </div>
      )}

      <Panel title="Email content">
        {email.suspicious && (
          <div className="mb-3 flex items-center gap-1.5 rounded-md border border-warning/30 bg-warning/8 px-2.5 py-1.5 text-xs text-warning">
            <Shield className="size-3.5" /> Links and embedded instructions are disabled while this message is flagged.
          </div>
        )}
        <p className="mono whitespace-pre-wrap text-sm text-muted-foreground">
          {email.body || email.snippet || "(no content captured)"}
        </p>
      </Panel>

      <Panel
        title="Reply draft"
        sub={pendingDraft ? "rotom drafted a reply — awaiting your review" : "No pending draft for this email"}
        actions={<RegenerateDraftButton emailId={email.id} hasDraft={Boolean(pendingDraft)} />}
      >
        {pendingDraft ? (
          <div className="space-y-3">
            <p className="whitespace-pre-wrap text-sm text-fg-2">{pendingDraft.body}</p>
            <div className="flex gap-2">
              <Button
                variant="default"
                size="sm"
                nativeButton={false}
                render={<Link href={`/email/drafts/${pendingDraft.id}`} />}
              >
                <PenLine /> Edit &amp; send
              </Button>
              <DiscardDraftButton draftId={pendingDraft.id} />
            </div>
          </div>
        ) : (
          <EmptyState
            icon="PenLine"
            title="No reply drafted yet"
            body="Generate an AI-assisted reply and review it before anything is sent."
          />
        )}
      </Panel>
    </div>
  );
}
