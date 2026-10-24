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
import type { CostPoint } from "@/lib/api";
import { formatUsd } from "@/lib/format/number";
import { bucketLabel } from "@/components/obs/runs-chart";

const PALETTE = ["var(--brand)", "var(--slate)", "var(--chart-3)", "var(--chart-4)", "var(--chart-5)", "var(--success)"];

/** Stacked spend per bucket by model. `buckets` fixes the x-axis (empty buckets show as gaps). */
export function SpendChart({
  points,
  buckets,
  bucket,
}: {
  points: CostPoint[];
  buckets: string[];
  bucket: "hour" | "day";
}) {
  const models = Array.from(new Set(points.map((p) => p.model))).sort();
  if (models.length === 0) {
    return <div className="flex h-56 items-center justify-center text-sm text-muted-foreground">No LLM calls in this window.</div>;
  }
  // Series keys are sanitized (s0, s1, ...): model names contain dots ("gemini-2.5-flash"), which
  // recharts' path-style dataKey lookup and CSS custom-property names both mishandle.
  const keyOf = new Map(models.map((m, i) => [m, `s${i}`]));
  const byBucket = new Map<string, Record<string, number>>();
  for (const p of points) {
    const row = byBucket.get(p.bucket) ?? {};
    const k = keyOf.get(p.model)!;
    row[k] = (row[k] ?? 0) + p.cost_usd;
    byBucket.set(p.bucket, row);
  }
  const data = buckets.map((b) => ({ label: bucketLabel(b, bucket), ...(byBucket.get(b) ?? {}) }));
  const config: ChartConfig = Object.fromEntries(
    models.map((m, i) => [`s${i}`, { label: m, color: PALETTE[i % PALETTE.length] }]),
  );
  return (
    <ChartContainer config={config} className="h-56 w-full">
      <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fontSize: 11 }} minTickGap={16} />
        <YAxis tickLine={false} axisLine={false} tick={{ fontSize: 11 }} width={52}
               tickFormatter={(v: number) => formatUsd(v)} />
        <ChartTooltip content={<ChartTooltipContent indicator="dot"
          formatter={(value, name) => (
            <span className="flex w-full justify-between gap-3">
              <span className="text-muted-foreground">{String(config[String(name)]?.label ?? name)}</span>
              <span className="font-mono tabular-nums">{formatUsd(Number(value))}</span>
            </span>
          )} />} />
        <ChartLegend content={<ChartLegendContent />} />
        {models.map((m, i) => (
          <Bar key={m} dataKey={`s${i}`} stackId="cost" fill={PALETTE[i % PALETTE.length]}
               radius={i === models.length - 1 ? [3, 3, 0, 0] : [0, 0, 0, 0]} />
        ))}
      </BarChart>
    </ChartContainer>
  );
}
