"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  XAxis,
  YAxis,
} from "recharts";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  ChartLegend,
  ChartLegendContent,
  type ChartConfig,
} from "@/components/ui/chart";
import type { UsageAggregation } from "@/lib/api";

interface TokensChartProps {
  usage: UsageAggregation[];
}

// Aggregate the raw usage rows into per-day buckets for the chart
function buildChartData(usage: UsageAggregation[]) {
  // Extract unique model names
  const modelsSet = new Set<string>();
  usage.forEach((r) => modelsSet.add(r.model || "unknown"));
  const models = Array.from(modelsSet).sort();

  // Group by calendar day (YYYY-MM-DD)
  const byDay: Record<string, Record<string, number>> = {};
  usage.forEach((row) => {
    const dateStr = row.day ? row.day.substring(0, 10) : "unknown";
    if (!byDay[dateStr]) byDay[dateStr] = {};
    const key = row.model || "unknown";
    byDay[dateStr][key] = (byDay[dateStr][key] ?? 0) + row.input_tokens + row.output_tokens;
  });

  // Sort days ascending
  const sortedDays = Object.keys(byDay).sort();
  const chartData = sortedDays.map((day) => ({
    day,
    label: day.substring(5), // MM-DD for brevity
    ...byDay[day],
  }));

  return { chartData, models };
}

// Token-based palette (near-monochrome + brand), reused across the chart.
const COLOURS = [
  "var(--brand)",
  "var(--slate)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
  "var(--success)",
  "var(--warning)",
  "var(--muted-foreground)",
];

export function TokensChart({ usage }: TokensChartProps) {
  if (!usage.length) {
    return (
      <div className="flex items-center justify-center h-40 text-muted-foreground text-sm">
        No usage data yet.
      </div>
    );
  }

  const { chartData, models } = buildChartData(usage);

  const chartConfig: ChartConfig = Object.fromEntries(
    models.map((m, i) => [
      m,
      { label: m, color: COLOURS[i % COLOURS.length] },
    ]),
  );

  return (
    <ChartContainer config={chartConfig} className="h-[280px] w-full">
      <BarChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis
          dataKey="label"
          tickLine={false}
          axisLine={false}
          tick={{ fontSize: 11 }}
        />
        <YAxis
          tickLine={false}
          axisLine={false}
          tick={{ fontSize: 11 }}
          tickFormatter={(v: number) =>
            v >= 1000 ? `${(v / 1000).toFixed(0)}k` : String(v)
          }
          width={40}
        />
        <ChartTooltip
          content={
            <ChartTooltipContent
              indicator="dot"
              labelFormatter={(label) => `Day: ${label}`}
            />
          }
        />
        <ChartLegend content={<ChartLegendContent />} />
        {models.map((model, i) => (
          <Bar
            key={model}
            dataKey={model}
            stackId="tokens"
            fill={COLOURS[i % COLOURS.length]}
            radius={i === models.length - 1 ? [4, 4, 0, 0] : [0, 0, 0, 0]}
          />
        ))}
      </BarChart>
    </ChartContainer>
  );
}
