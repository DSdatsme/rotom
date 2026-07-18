import * as React from "react";
import { cn } from "@/lib/utils";
import { Icon } from "@/components/ui/icon";

/** Centered empty state with icon, title, optional body + action. */
export function EmptyState({
  icon = "Inbox",
  title,
  body,
  action,
  className,
}: {
  icon?: string;
  title: string;
  body?: string;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center justify-center px-6 py-12 text-center", className)}>
      <div className="mb-3 grid size-10 place-items-center rounded-lg border border-border bg-card-3 text-muted-foreground">
        <Icon name={icon} size={20} />
      </div>
      <p className="text-sm font-medium text-foreground">{title}</p>
      {body && <p className="mt-1 max-w-sm text-xs text-muted-foreground">{body}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
