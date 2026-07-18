"use client";

import { useTransition } from "react";
import { useRouter } from "next/navigation";
import { Loader, Trash2 } from "lucide-react";

import { discardDraftInline } from "@/lib/actions";

export function DiscardDraftButton({ draftId }: { draftId: number }) {
  const [pending, startTransition] = useTransition();
  const router = useRouter();

  return (
    <button
      className="dc-discard relative z-10"
      disabled={pending}
      title="Discard draft"
      aria-label="Discard draft"
      onClick={(e) => {
        e.stopPropagation();
        startTransition(async () => {
          const r = await discardDraftInline(draftId);
          if (r.ok) router.refresh();
        });
      }}
    >
      {pending ? <Loader size={15} className="animate-spin" /> : <Trash2 size={15} />}
    </button>
  );
}
