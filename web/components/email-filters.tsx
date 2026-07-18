"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Filter,
  CircleDot,
  AtSign,
  SlidersHorizontal,
  Calendar,
  Clock,
  Shield,
  ChevronDown,
  Check,
  CircleX,
} from "lucide-react";

export interface EmailFilterValues {
  category: string;
  account: string;
  status: string;
  suspicious: string;
  urgency: string;
  received_from: string;
  received_to: string;
  triaged_from: string;
  triaged_to: string;
}

type Opt = { value: string; label: string; swatch?: string };

const CATEGORY_OPTIONS: Opt[] = [
  { value: "critical", label: "Critical", swatch: "danger" },
  { value: "needs_reply", label: "Needs reply", swatch: "accent" },
  { value: "fyi", label: "FYI", swatch: "slate" },
  { value: "skip", label: "Skip", swatch: "muted" },
];
const STATUS_OPTIONS: Opt[] = [
  { value: "open", label: "Open", swatch: "accent" },
  { value: "done", label: "Done", swatch: "success" },
  { value: "irrelevant", label: "Irrelevant", swatch: "muted" },
];
const URGENCY_OPTIONS: Opt[] = [
  { value: "3", label: "High" },
  { value: "2", label: "Medium" },
  { value: "1", label: "Low" },
  { value: "0", label: "None" },
];
const DATE_OPTIONS: Opt[] = [
  { value: "", label: "Any time" },
  { value: "0", label: "Today" },
  { value: "2", label: "Last 3 days" },
  { value: "6", label: "Last 7 days" },
];

const DEFAULTS = { category: "critical,needs_reply", status: "open" };

function isoDaysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

/** Mock facet dropdown — multi (checkboxes) or single (presets). */
function Facet({
  label,
  icon: IconCmp,
  options,
  selected,
  onChange,
  multi = true,
}: {
  label: string;
  icon: typeof Filter;
  options: Opt[];
  selected: string[];
  onChange: (next: string[]) => void;
  multi?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [open]);

  const active = multi ? selected.length > 0 : selected[0] !== undefined && selected[0] !== "";
  const summary = multi
    ? selected.length || null
    : active
      ? options.find((o) => o.value === selected[0])?.label
      : null;

  const toggle = (value: string) => {
    if (multi) {
      onChange(selected.includes(value) ? selected.filter((v) => v !== value) : [...selected, value]);
    } else {
      onChange(value ? [value] : []);
      setOpen(false);
    }
  };

  return (
    <div className="facet-wrap" ref={ref}>
      <button className={"facet" + (active ? " active" : "")} onClick={() => setOpen((o) => !o)}>
        <IconCmp size={13} />
        <span>{label}</span>
        {summary != null && <span className="facet-count">{summary}</span>}
        <ChevronDown size={13} className="facet-caret" />
      </button>
      {open && (
        <div className="facet-pop">
          {options.map((o) => {
            const on = multi ? selected.includes(o.value) : selected[0] === o.value || (!selected[0] && o.value === "");
            return (
              <button key={o.value || "any"} className="facet-opt" onClick={() => toggle(o.value)}>
                <span className={"facet-check" + (on ? " on" : "")}>{on && <Check size={11} />}</span>
                {o.swatch && <span className={"facet-swatch tone-" + o.swatch} />}
                <span className="facet-opt-label">{o.label}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function EmailFilters({ accounts, values }: { accounts: string[]; values: EmailFilterValues }) {
  const router = useRouter();

  // Selections live in the URL — every change navigates, the server refetches.
  const apply = (patch: Partial<EmailFilterValues>) => {
    const next = { ...values, ...patch };
    const params = new URLSearchParams();
    for (const [k, v] of Object.entries(next)) if (v) params.set(k, v);
    params.set("f", "1"); // marks "user touched filters" so defaults don't reapply
    router.replace(`/email?${params.toString()}`);
  };

  const csv = (s: string) => (s ? s.split(",") : []);
  // single-select date preset: current value -> the "days ago" option that produced it
  const datePreset = (from: string) => {
    if (!from) return [] as string[];
    for (const o of DATE_OPTIONS) if (o.value && isoDaysAgo(Number(o.value)) === from) return [o.value];
    return [] as string[];
  };
  const applyDate = (field: "received_from" | "triaged_from") => (vals: string[]) =>
    apply({ [field]: vals[0] ? isoDaysAgo(Number(vals[0])) : "" });

  const suspicious = values.suspicious === "true";
  const acctOpts: Opt[] = accounts.map((a) => ({ value: a, label: a }));

  const dirty =
    values.category !== DEFAULTS.category ||
    values.status !== DEFAULTS.status ||
    !!(values.account || values.urgency || values.suspicious || values.received_from || values.triaged_from);

  return (
    <div className="filter-bar">
      <Facet label="Category" icon={Filter} options={CATEGORY_OPTIONS} selected={csv(values.category)} onChange={(v) => apply({ category: v.join(",") })} />
      <Facet label="Status" icon={CircleDot} options={STATUS_OPTIONS} selected={csv(values.status)} onChange={(v) => apply({ status: v.join(",") })} />
      <Facet label="Account" icon={AtSign} options={acctOpts} selected={csv(values.account)} onChange={(v) => apply({ account: v.join(",") })} />
      <Facet label="Urgency" icon={SlidersHorizontal} options={URGENCY_OPTIONS} selected={csv(values.urgency)} onChange={(v) => apply({ urgency: v.join(",") })} />
      <Facet label="Received" icon={Calendar} options={DATE_OPTIONS} selected={datePreset(values.received_from)} onChange={applyDate("received_from")} multi={false} />
      <Facet label="Triaged" icon={Clock} options={DATE_OPTIONS} selected={datePreset(values.triaged_from)} onChange={applyDate("triaged_from")} multi={false} />

      <button className={"susp-toggle" + (suspicious ? " active" : "")} onClick={() => apply({ suspicious: suspicious ? "" : "true" })}>
        <Shield size={13} />
        <span>Suspicious only</span>
      </button>

      {dirty && (
        <button className="filter-reset" onClick={() => router.replace("/email")}>
          <CircleX size={13} />
          <span>Reset</span>
        </button>
      )}
    </div>
  );
}
