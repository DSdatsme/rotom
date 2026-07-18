"use client";

import { useTransition } from "react";
import { useRouter } from "next/navigation";
import { Check, CircleSlash, Loader2, RotateCcw } from "lucide-react";

import { setEmailsStatus } from "@/lib/actions";
import { Button } from "@/components/ui/button";

export function EmailStatusButtons({ emailId, status }: { emailId: number; status: string }) {
  const [pending, startTransition] = useTransition();
  const router = useRouter();

  const set = (next: "done" | "irrelevant" | "open") =>
    startTransition(async () => {
      const r = await setEmailsStatus([emailId], next);
      if (r.ok) router.refresh();
    });

  return (
    <div className="flex gap-2">
      {status !== "done" ? (
        <Button size="sm" variant="secondary" disabled={pending} onClick={() => set("done")}>
          {pending ? <Loader2 className="animate-spin" /> : <Check />} Done
        </Button>
      ) : null}
      {status !== "irrelevant" ? (
        <Button size="sm" variant="secondary" disabled={pending} onClick={() => set("irrelevant")}>
          <CircleSlash /> Irrelevant
        </Button>
      ) : null}
      {status !== "open" ? (
        <Button size="sm" variant="ghost" disabled={pending} onClick={() => set("open")}>
          <RotateCcw /> Reopen
        </Button>
      ) : null}
    </div>
  );
}
