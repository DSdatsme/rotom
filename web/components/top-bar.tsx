"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Search, ChevronRight } from "lucide-react";

import { SidebarTrigger } from "@/components/ui/sidebar";
import { StatusDot } from "@/components/ui/status-dot";
import { Kbd } from "@/components/ui/kbd";
import { breadcrumbFor } from "@/lib/nav";

export function TopBar({ onOpenPalette }: { onOpenPalette: () => void }) {
  const pathname = usePathname();
  const crumbs = breadcrumbFor(pathname);

  return (
    <header className="sticky top-0 z-30 flex h-13 items-center justify-between gap-3 border-b border-border bg-sidebar/80 px-3 backdrop-blur">
      <div className="flex min-w-0 items-center gap-2">
        <SidebarTrigger />
        <div className="h-5 w-px bg-border" />
        <nav className="flex min-w-0 items-center gap-1 text-sm" aria-label="Breadcrumb">
          {crumbs.map((c, i) => {
            const last = i === crumbs.length - 1;
            return (
              <span key={i} className="flex min-w-0 items-center gap-1">
                {i > 0 && <ChevronRight className="size-3.5 shrink-0 text-faint" />}
                {last || !c.href ? (
                  <span className={last ? "truncate font-semibold text-foreground" : "text-muted-foreground"}>
                    {c.label}
                  </span>
                ) : (
                  <Link href={c.href} className="text-muted-foreground hover:text-foreground hover:underline">
                    {c.label}
                  </Link>
                )}
              </span>
            );
          })}
        </nav>
      </div>
      <div className="flex items-center gap-3">
        <button
          onClick={onOpenPalette}
          className="flex items-center gap-2 rounded-lg border border-border bg-card px-2.5 py-1.5 text-sm text-muted-foreground hover:bg-accent"
          aria-label="Open command palette"
        >
          <Search className="size-3.5" />
          <span className="hidden sm:inline">Search or jump to…</span>
          <span className="hidden items-center gap-0.5 sm:flex">
            <Kbd>⌘</Kbd>
            <Kbd>K</Kbd>
          </span>
        </button>
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground" title="API connected">
          <StatusDot tone="success" pulse />
          <span className="hidden md:inline">Live</span>
        </div>
      </div>
    </header>
  );
}
