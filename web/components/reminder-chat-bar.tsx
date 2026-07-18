"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Check, Loader2, SendHorizonal, Sparkles, X } from "lucide-react";

import { createReminderAction, parseReminderAction } from "@/lib/actions";
import type { ReminderProposal } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

export function ReminderChatBar() {
  const [message, setMessage] = useState("");
  const [proposal, setProposal] = useState<ReminderProposal | null>(null);
  const [error, setError] = useState("");
  const [parsing, startParse] = useTransition();
  const [confirming, startConfirm] = useTransition();
  const router = useRouter();

  const parse = () => {
    if (!message.trim() || parsing) return;
    startParse(async () => {
      setError("");
      setProposal(null);
      const r = await parseReminderAction(message);
      if (r.ok && r.proposal) setProposal(r.proposal);
      else setError(r.error ?? "Could not understand that — try rephrasing.");
    });
  };

  const confirm = () => {
    if (!proposal) return;
    startConfirm(async () => {
      const r = await createReminderAction(proposal.text, proposal.fire_at, proposal.recurrence_cron);
      if (!r.ok) {
        setError(r.error ?? "Failed to create reminder");
        return;
      }
      setProposal(null);
      setMessage("");
      router.refresh();
    });
  };

  return (
    <div className="sticky bottom-0 -mx-1 space-y-2 border-t bg-background px-1 pb-2 pt-3">
      {proposal ? (
        <Card>
          <CardContent className="flex flex-wrap items-center justify-between gap-3 py-3">
            <div className="space-y-0.5">
              <p className="text-sm font-medium">⏰ {proposal.confirmation}</p>
              <p className="text-xs text-muted-foreground">
                {new Date(proposal.fire_at).toLocaleString(undefined, {
                  weekday: "short",
                  month: "short",
                  day: "numeric",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
                {proposal.recurrence_cron ? ` · repeats (${proposal.recurrence_cron})` : ""}
              </p>
            </div>
            <div className="flex gap-2">
              <Button size="sm" data-rotom-wink onClick={confirm} disabled={confirming}>
                {confirming ? <Loader2 className="animate-spin" /> : <Check />} Confirm
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setProposal(null)} disabled={confirming}>
                <X /> Discard
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {error ? <p className="text-xs text-destructive">{error}</p> : null}

      <div className="flex gap-2">
        <Input
          placeholder='Try: "remind me to call mom tomorrow at 3pm" or "standup notes every monday 9am"'
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") parse();
          }}
          disabled={parsing}
        />
        <Button onClick={parse} disabled={parsing || !message.trim()}>
          {parsing ? <Loader2 className="animate-spin" /> : <SendHorizonal />}
        </Button>
      </div>
      <p className="flex items-center gap-1 text-[11px] text-muted-foreground">
        <Sparkles className="h-3 w-3" /> Natural language — you confirm before anything is scheduled.
      </p>
    </div>
  );
}
