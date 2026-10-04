import Link from "next/link";
import { cn } from "@/lib/utils";

/** Server-rendered segmented control that sets one search param. */
export function WindowTabs({
  param,
  value,
  options,
  basePath,
}: {
  param: string;
  value: string;
  options: { value: string; label: string }[];
  basePath: string;
}) {
  return (
    <div className="inline-flex rounded-md border border-border bg-card p-0.5 text-xs">
      {options.map((o) => (
        <Link
          key={o.value}
          href={`${basePath}?${param}=${o.value}`}
          className={cn(
            "rounded px-2.5 py-1 font-medium transition-colors",
            o.value === value ? "bg-brand-soft text-brand" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {o.label}
        </Link>
      ))}
    </div>
  );
}
