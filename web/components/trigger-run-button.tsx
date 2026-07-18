"use client";
import { useTransition } from "react";
import { triggerRunAction } from "@/lib/actions";
import { Zap, Loader } from "lucide-react";

export function TriggerRunButton() {
  const [pending, startTransition] = useTransition();

  const handleTrigger = () => {
    startTransition(async () => {
      try {
        await triggerRunAction();
      } catch (e) {
        console.error(e);
      }
    });
  };

  return (
    <button className="btn btn-primary btn-md" data-rotom-wink onClick={handleTrigger} disabled={pending}>
      {pending ? <Loader size={15} className="animate-spin" /> : <Zap size={15} />}
      <span>{pending ? "Starting…" : "Trigger run"}</span>
    </button>
  );
}
