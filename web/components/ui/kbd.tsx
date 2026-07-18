import * as React from "react";
import { cn } from "@/lib/utils";

/** Keyboard key cap. */
export function Kbd({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <kbd
      className={cn(
        "inline-flex h-5 min-w-5 items-center justify-center rounded-[6px] border border-border bg-card-3 px-1.5 font-mono text-[11px] text-muted-foreground",
        className,
      )}
    >
      {children}
    </kbd>
  );
}
