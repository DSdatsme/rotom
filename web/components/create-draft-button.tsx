"use client";
import { useTransition } from "react";
import { Plus, Loader } from "lucide-react";
import { createDraftAction } from "@/lib/actions";
import { useRouter } from "next/navigation";

export function CreateDraftButton() {
  const [pending, startTransition] = useTransition();
  const router = useRouter();

  return (
    <button
      className="btn btn-primary btn-md"
      data-rotom-wink
      disabled={pending}
      onClick={() => {
        startTransition(async () => {
          const res = await createDraftAction("outreach");
          if (res.ok && res.draft) {
            router.push(`/email/drafts/${res.draft.id}`);
          }
        });
      }}
    >
      {pending ? <Loader size={15} className="animate-spin" /> : <Plus size={15} />}
      <span>New outreach</span>
    </button>
  );
}
