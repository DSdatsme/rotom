import type { Tone } from "@/lib/view/email";

/**
 * Badge styling per semantic tone — matches the mockup recipe:
 * colored text + a colored border + a soft background tint.
 */
export const toneBadge: Record<Tone, string> = {
  danger: "border border-destructive/35 bg-destructive/12 text-destructive",
  warning: "border border-warning/40 bg-warning/12 text-warning",
  success: "border border-success/35 bg-success/12 text-success",
  brand: "border border-brand-line bg-brand-soft text-brand",
  slate: "border border-slate/35 bg-slate/12 text-slate",
  muted: "border border-border bg-card-3 text-muted-foreground",
};

/** Solid dot color per tone. */
export const toneDot: Record<Tone, string> = {
  danger: "bg-destructive",
  warning: "bg-warning",
  success: "bg-success",
  brand: "bg-brand",
  slate: "bg-slate",
  muted: "bg-muted-foreground",
};

/** Foreground text color per tone. */
export const toneText: Record<Tone, string> = {
  danger: "text-destructive",
  warning: "text-warning",
  success: "text-success",
  brand: "text-brand",
  slate: "text-slate",
  muted: "text-muted-foreground",
};
