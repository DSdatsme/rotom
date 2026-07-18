"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Search, CornerDownLeft } from "lucide-react";

import { rankPalette, type PaletteAction, type PalettePage } from "@/lib/command-palette/fuzzy";
import { flattenNav } from "@/lib/nav";
import { Icon } from "@/components/ui/icon";
import { Kbd } from "@/components/ui/kbd";

const PAGES: PalettePage[] = flattenNav().map((i) => ({
  id: i.href,
  label: i.title,
  group: i.group,
  href: i.href,
  icon: i.icon,
}));

const ACTIONS: PaletteAction[] = [
  { id: "/email/drafts", label: "New draft", icon: "PenLine", hint: "Compose a reply or outreach", kbd: "D" },
  { id: "/reminders", label: "New reminder", icon: "Bell", hint: "Schedule a one-off or recurring reminder", kbd: "R" },
  { id: "/email/runs", label: "View runs", icon: "History", hint: "Background tasks & triage logs", kbd: "N" },
];

export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const [q, setQ] = React.useState("");
  const [sel, setSel] = React.useState(0);
  const inputRef = React.useRef<HTMLInputElement>(null);

  const sections = React.useMemo(() => rankPalette(q, { pages: PAGES, actions: ACTIONS }), [q]);
  const flat = React.useMemo(() => sections.flatMap((s) => s.rows), [sections]);

  React.useEffect(() => {
    if (open) {
      setQ("");
      setSel(0);
      const id = setTimeout(() => inputRef.current?.focus(), 20);
      return () => clearTimeout(id);
    }
  }, [open]);

  React.useEffect(() => setSel(0), [q]);

  if (!open) return null;

  function go(href: string) {
    router.push(href);
    onClose();
  }

  function onKey(e: React.KeyboardEvent) {
    if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setSel((s) => Math.min(s + 1, flat.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSel((s) => Math.max(s - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const row = flat[sel];
      if (row?.href) go(row.href);
      else if (row) go(row.id);
    }
  }

  let idx = -1;
  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 pt-[12vh]"
      onMouseDown={onClose}
    >
      <div
        className="w-full max-w-lg overflow-hidden rounded-xl border border-border bg-card shadow-2xl"
        role="dialog"
        aria-label="Command palette"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-border px-3.5">
          <Search className="size-4 shrink-0 text-muted-foreground" />
          <input
            ref={inputRef}
            className="h-12 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            placeholder="Search or jump to…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={onKey}
            aria-label="Command palette search"
          />
          <Kbd>Esc</Kbd>
        </div>
        <div className="max-h-[52vh] overflow-y-auto p-1.5">
          {flat.length === 0 && (
            <div className="flex flex-col items-center gap-1.5 px-4 py-10 text-sm text-muted-foreground">
              <Search className="size-4" />
              <span>No results for “{q}”</span>
            </div>
          )}
          {sections.map((sec) => (
            <div key={sec.header} className="mb-1">
              <div className="px-2.5 py-1.5 text-[11px] font-semibold tracking-wide text-faint uppercase">
                {sec.header}
              </div>
              {sec.rows.map((row) => {
                idx += 1;
                const i = idx;
                const active = i === sel;
                return (
                  <button
                    key={row.type + row.id}
                    className={
                      "flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-sm " +
                      (active ? "bg-accent text-foreground" : "text-fg-2")
                    }
                    onMouseMove={() => setSel(i)}
                    onClick={() => go(row.href ?? row.id)}
                  >
                    <span className="text-muted-foreground">
                      <Icon name={row.icon ?? "CircleDot"} size={16} />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate">{row.label}</span>
                      {row.hint && <span className="block truncate text-xs text-muted-foreground">{row.hint}</span>}
                    </span>
                    {row.group && <span className="text-xs text-faint">{row.group}</span>}
                    {row.kbd && <Kbd>{row.kbd}</Kbd>}
                    {active && <CornerDownLeft className="size-3.5 text-muted-foreground" />}
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
