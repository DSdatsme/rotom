"use client";

import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import type { RunsBucket } from "@/lib/api";
import { normalizeTs } from "@/lib/obs-utils";

const SERIES: { key: keyof Omit<RunsBucket, "bucket">; label: string; color: string }[] = [
  { key: "success", label: "Success", color: "var(--success)" },
  { key: "degraded", label: "Degraded", color: "var(--warning)" },
  { key: "interrupted", label: "Interrupted", color: "var(--slate)" },
  { key: "failure", label: "Failed", color: "var(--destructive)" },
  { key: "running", label: "Running", color: "var(--brand)" },
];

export function bucketLabel(iso: string, bucket: "hour" | "day"): string {
  const d = new Date(normalizeTs(iso));
  return bucket === "hour"
    ? d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false })
    : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function RunsChart({ series, bucket }: { series: RunsBucket[]; bucket: "hour" | "day" }) {
  if (!series.some((b) => SERIES.some((s) => b[s.key] > 0))) {
    return <div className="flex h-56 items-center justify-center text-sm text-muted-foreground">No runs in this window.</div>;
  }
  const config: ChartConfig = Object.fromEntries(SERIES.map((s) => [s.key, { label: s.label, color: s.color }]));
  const data = series.map((b) => ({ ...b, label: bucketLabel(b.bucket, bucket) }));
  return (
    <ChartContainer config={config} className="h-56 w-full">
      <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fontSize: 11 }} minTickGap={16} />
        <YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={{ fontSize: 11 }} width={28} />
        <ChartTooltip content={<ChartTooltipContent indicator="dot" />} />
        <ChartLegend content={<ChartLegendContent />} />
        {SERIES.map((s, i) => (
          <Bar key={s.key} dataKey={s.key} stackId="runs" fill={s.color}
               radius={i === SERIES.length - 1 ? [3, 3, 0, 0] : [0, 0, 0, 0]} />
        ))}
      </BarChart>
    </ChartContainer>
  );
}
