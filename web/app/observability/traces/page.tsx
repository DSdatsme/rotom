import Link from "next/link";
import { getTraces } from "@/lib/api";
import { Panel } from "@/components/ui/panel";
import { EmptyState } from "@/components/ui/empty-state";
import { TracesTable } from "@/components/obs/traces-table";
import { cn } from "@/lib/utils";

export const dynamic = "force-dynamic";

type Search = { type?: string; status?: string; q?: string; before?: string };

const TYPES = [
  { value: "", label: "All" },
  { value: "run", label: "Runs" },
  { value: "chat", label: "Chat" },
  { value: "http", label: "API" },
];
const STATUSES = [
  { value: "", label: "Any status" },
  { value: "error", label: "Errors" },
];

function href(base: Search, patch: Partial<Search>): string {
  const merged = { ...base, ...patch };
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(merged)) if (v) p.set(k, v);
  const qs = p.toString();
  return `/observability/traces${qs ? `?${qs}` : ""}`;
}

function Pills({ items, current, keyName, search }: {
  items: { value: string; label: string }[]; current: string; keyName: keyof Search; search: Search;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((i) => (
        <Link key={i.value} href={href(search, { [keyName]: i.value, before: undefined })}
              className={cn("rounded-full border px-3 py-1 text-xs",
                current === i.value ? "border-brand-line bg-brand-soft text-brand" : "border-border text-muted-foreground hover:text-foreground")}>
          {i.label}
        </Link>
      ))}
    </div>
  );
}

export default async function TracesPage({ searchParams }: { searchParams: Promise<Search> }) {
  const search = await searchParams;
  // eslint-disable-next-line react-hooks/purity -- server component; request-time clock
  const now = Date.now();
  let page;
  try {
    page = await getTraces({ ...search, limit: 50 });
  } catch (e) {
    return (
      <Panel>
        <EmptyState icon="TriangleAlert" title="Couldn't load traces" body={e instanceof Error ? e.message : undefined} />
      </Panel>
    );
  }
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Traces</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          One trace per run, chat turn or API action — every step, LLM call and tool call inside it.
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Pills items={TYPES} current={search.type ?? ""} keyName="type" search={search} />
        <Pills items={STATUSES} current={search.status ?? ""} keyName="status" search={search} />
        <form action="/observability/traces" className="ml-auto">
          {search.type && <input type="hidden" name="type" value={search.type} />}
          {search.status && <input type="hidden" name="status" value={search.status} />}
          <input name="q" defaultValue={search.q ?? ""} placeholder="Filter by name…"
                 className="h-8 w-56 rounded-md border border-border bg-card px-2.5 text-sm" />
        </form>
      </div>
      <Panel noPad>
        {page.traces.length === 0 ? (
          <EmptyState icon="Waypoints" title="No traces yet"
                      body="Traces appear when a run finishes, you chat with rotom, or an action is taken in the dashboard." />
        ) : (
          <TracesTable traces={page.traces} now={now} />
        )}
      </Panel>
      {page.next_before && (
        <div className="flex justify-center">
          <Link href={href(search, { before: page.next_before })} className="text-sm text-brand hover:underline">
            Older traces →
          </Link>
        </div>
      )}
    </div>
  );
}
