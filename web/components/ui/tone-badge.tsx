import * as React from "react";
import { cn } from "@/lib/utils";
import { toneBadge } from "@/lib/tone";
import type { Tone } from "@/lib/view/email";
import { Icon } from "@/components/ui/icon";

/** Small pill badge keyed by semantic tone, with an optional leading icon. */
export function ToneBadge({
  tone,
  icon,
  children,
  className,
}: {
  tone: Tone;
  icon?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex h-5 w-fit items-center gap-1 rounded-full px-2 text-xs font-medium whitespace-nowrap",
        toneBadge[tone],
        className,
      )}
    >
      {icon && <Icon name={icon} size={12} />}
      {children}
    </span>
  );
}
