"use client";

import * as React from "react";
import { useRouter } from "next/navigation";

import { TopBar } from "@/components/top-bar";
import { CommandPalette } from "@/components/command-palette";

const GOTO: Record<string, string> = {
  h: "/",
  i: "/email",
  d: "/email/drafts",
  r: "/reminders",
  u: "/observability",
  l: "/observability/logs",
  s: "/soul",
  n: "/email/runs",
};

export function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [paletteOpen, setPaletteOpen] = React.useState(false);
  const gKey = React.useRef(false);

  React.useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const el = e.target as HTMLElement;
      const typing = /^(input|textarea|select)$/i.test(el?.tagName ?? "") || el?.isContentEditable;
      const mod = e.metaKey || e.ctrlKey;

      if (mod && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((o) => !o);
        return;
      }
      if (typing || mod) return;

      if (e.key === "g") {
        gKey.current = true;
        setTimeout(() => (gKey.current = false), 700);
        return;
      }
      if (gKey.current) {
        const href = GOTO[e.key.toLowerCase()];
        if (href) {
          e.preventDefault();
          router.push(href);
          gKey.current = false;
        }
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [router]);

  return (
    <main className="flex min-w-0 flex-1 flex-col">
      <TopBar onOpenPalette={() => setPaletteOpen(true)} />
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-[1440px] px-6 py-7">{children}</div>
      </div>
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </main>
  );
}
