"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Loader2, RefreshCw } from "lucide-react";

import { regenerateDraft } from "@/lib/actions";
import { Button } from "@/components/ui/button";

export function RegenerateDraftButton({ emailId, hasDraft }: { emailId: number; hasDraft: boolean }) {
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const router = useRouter();

  return (
    <div className="flex items-center gap-2">
      {error ? <span className="text-xs text-destructive">{error}</span> : null}
      <Button
        variant="outline"
        size="sm"
        disabled={pending}
        onClick={() => {
          setError(null);
          startTransition(async () => {
            const r = await regenerateDraft(emailId);
            if (!r.ok) setError(r.error ?? "failed");
            else router.refresh();
          });
        }}
      >
        {pending ? <Loader2 className="animate-spin" /> : <RefreshCw />}
        {hasDraft ? "Regenerate" : "Generate draft"}
      </Button>
    </div>
  );
}
