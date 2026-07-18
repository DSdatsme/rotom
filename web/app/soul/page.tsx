import { Sparkles, Info, Activity, CornerDownLeft, PenLine } from "lucide-react";

import { getSoul } from "@/lib/api";
import { SoulEditor } from "./soul-editor";

export const dynamic = "force-dynamic";

const HINTS = [
  { icon: Info, label: "Background", hint: "Who you are, your role, what you care about." },
  { icon: Activity, label: "Tone & voice", hint: "Formal or casual? Words you love and ban." },
  { icon: CornerDownLeft, label: "Situations", hint: "How you schedule, decline, deliver bad news." },
  { icon: PenLine, label: "Writing samples", hint: "A few real lines rotom can echo (prefix with >)." },
];

export default async function SoulPage() {
  const soul = await getSoul().catch(() => ({ content: "" }));

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">SOUL Persona</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Define your background, tone, and writing samples. rotom uses this to mimic your style.
        </p>
      </div>

      <div className="flex items-start gap-3 rounded-lg border border-brand-line/40 bg-brand-soft px-4 py-3 text-sm text-fg-2">
        <Sparkles className="mt-0.5 size-4 shrink-0 text-brand" />
        <span>
          This document shapes <strong className="text-foreground">every reply rotom writes.</strong> The more
          honest and specific you are about your voice, the more its drafts sound like you.
        </span>
      </div>

      <div className="grid gap-5 lg:grid-cols-[1fr_280px]">
        <SoulEditor initialContent={soul.content} />

        <aside className="space-y-3">
          <div className="text-xs font-semibold tracking-wide text-faint uppercase">What to include</div>
          <div className="space-y-2.5">
            {HINTS.map((h) => (
              <div key={h.label} className="flex gap-2.5 rounded-lg border border-border bg-card p-3">
                <span className="grid size-7 shrink-0 place-items-center rounded-md bg-card-3 text-muted-foreground">
                  <h.icon className="size-3.5" />
                </span>
                <div>
                  <div className="text-sm font-medium">{h.label}</div>
                  <div className="text-xs text-muted-foreground">{h.hint}</div>
                </div>
              </div>
            ))}
          </div>
          <p className="flex items-start gap-1.5 px-1 text-xs text-faint">
            <Info className="mt-0.5 size-3 shrink-0" />
            It&apos;s free-form — these are guides. Write it the way you&apos;d brief a new assistant.
          </p>
        </aside>
      </div>
    </div>
  );
}
