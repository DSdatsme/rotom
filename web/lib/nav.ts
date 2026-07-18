export interface NavItem {
  title: string;
  href: string;
  icon: string; // lucide export name
}
export interface NavSection {
  label: string;
  items: NavItem[];
}

export const NAV_SECTIONS: NavSection[] = [
  { label: "Overview", items: [{ title: "Home", href: "/", icon: "House" }] },
  {
    label: "Email",
    items: [
      { title: "Inbox triage", href: "/email", icon: "Inbox" },
      { title: "Drafts", href: "/email/drafts", icon: "PenLine" },
      { title: "Runs", href: "/email/runs", icon: "History" },
    ],
  },
  { label: "Workspace", items: [{ title: "Reminders", href: "/reminders", icon: "Bell" }] },
  { label: "Settings", items: [{ title: "SOUL Persona", href: "/soul", icon: "Sparkles" }] },
  {
    label: "Observability",
    items: [
      { title: "Usage & Metrics", href: "/observability", icon: "ChartColumn" },
      { title: "Logs", href: "/observability/logs", icon: "ScrollText" },
    ],
  },
];

export function flattenNav(): Array<NavItem & { group: string }> {
  return NAV_SECTIONS.flatMap((s) => s.items.map((i) => ({ ...i, group: s.label })));
}

export interface Crumb {
  label: string;
  href?: string;
}

const DETAIL_BASES: Array<{
  test: RegExp;
  section: string;
  leafHref: string;
  leafLabel: string;
}> = [
  { test: /^\/email\/runs\/[^/]+$/, section: "Email", leafHref: "/email/runs", leafLabel: "Runs" },
  { test: /^\/email\/drafts\/[^/]+$/, section: "Email", leafHref: "/email/drafts", leafLabel: "Drafts" },
  { test: /^\/email\/[^/]+$/, section: "Email", leafHref: "/email", leafLabel: "Inbox triage" },
];

export function breadcrumbFor(pathname: string, opts?: { title?: string }): Crumb[] {
  for (const s of NAV_SECTIONS) {
    for (const i of s.items) {
      if (i.href === pathname) return [{ label: s.label }, { label: i.title, href: i.href }];
    }
  }
  for (const d of DETAIL_BASES) {
    if (d.test.test(pathname)) {
      return [
        { label: d.section },
        { label: d.leafLabel, href: d.leafHref },
        { label: opts?.title ?? "Detail" },
      ];
    }
  }
  return [{ label: "Overview" }, { label: "Home", href: "/" }];
}
