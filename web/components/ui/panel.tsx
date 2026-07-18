import * as React from "react";
import { cn } from "@/lib/utils";

/** The one reusable container: optional header strip (title/sub/actions) + body. */
export function Panel({
  title,
  sub,
  actions,
  children,
  className,
  bodyClassName,
  noPad = false,
}: {
  title?: React.ReactNode;
  sub?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bodyClassName?: string;
  noPad?: boolean;
}) {
  return (
    <section className={cn("rounded-lg border border-border bg-card", className)}>
      {(title || actions) && (
        <header className="flex items-start justify-between gap-3 border-b border-border px-4 py-3">
          <div className="min-w-0">
            {title && <h2 className="text-sm font-semibold tracking-tight text-foreground">{title}</h2>}
            {sub && <p className="mt-0.5 text-xs text-muted-foreground">{sub}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cn(!noPad && "p-4", bodyClassName)}>{children}</div>
    </section>
  );
}
