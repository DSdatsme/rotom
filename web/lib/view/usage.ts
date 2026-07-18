import type { UsageAggregation } from "@/lib/api";

export interface DayBucket {
  day: string;
  models: Record<string, number>;
}

/** Group rows by day; per-day token totals per model (input+output). */
export function aggregateByDay(rows: UsageAggregation[]): DayBucket[] {
  const byDay = new Map<string, Record<string, number>>();
  for (const r of rows) {
    const models = byDay.get(r.day) ?? {};
    models[r.model] = (models[r.model] ?? 0) + r.input_tokens + r.output_tokens;
    byDay.set(r.day, models);
  }
  return [...byDay.entries()]
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .map(([day, models]) => ({ day, models }));
}

/** Distinct model series across all rows (chart legend / stacked keys). */
export function modelSeries(rows: UsageAggregation[]): string[] {
  return [...new Set(rows.map((r) => r.model))];
}

export interface UsageKpis {
  totalTokens: number;
  input: number;
  output: number;
  avgLatencyMs: number;
}

export function usageKpis(rows: UsageAggregation[]): UsageKpis {
  if (rows.length === 0) return { totalTokens: 0, input: 0, output: 0, avgLatencyMs: 0 };
  let input = 0,
    output = 0,
    latSum = 0,
    latN = 0;
  for (const r of rows) {
    input += r.input_tokens;
    output += r.output_tokens;
    if (r.avg_latency_ms != null) {
      latSum += r.avg_latency_ms;
      latN += 1;
    }
  }
  return {
    totalTokens: input + output,
    input,
    output,
    avgLatencyMs: latN ? Math.round(latSum / latN) : 0,
  };
}
