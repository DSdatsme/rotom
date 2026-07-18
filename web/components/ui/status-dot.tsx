import { cn } from "@/lib/utils";
import { toneDot } from "@/lib/tone";
import type { Tone } from "@/lib/view/email";

/** Small status dot; `pulse` adds a soft ping for live/active states. */
export function StatusDot({
  tone = "success",
  pulse = false,
  className,
}: {
  tone?: Tone;
  pulse?: boolean;
  className?: string;
}) {
  return (
    <span className={cn("relative inline-flex h-2 w-2", className)} aria-hidden>
      {pulse && (
        <span className={cn("absolute inset-0 animate-ping rounded-full opacity-60", toneDot[tone])} />
      )}
      <span className={cn("relative inline-flex h-2 w-2 rounded-full", toneDot[tone])} />
    </span>
  );
}
