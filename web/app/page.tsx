import Link from "next/link";
import { ArrowUp, Zap, PenLine, Bell, GitBranch, SquareKanban, Calendar, ChevronRight, TriangleAlert } from "lucide-react";

import { getDrafts, getEmails, getReminders } from "@/lib/api";
import { Panel } from "@/components/ui/panel";
import { EmptyState } from "@/components/ui/empty-state";
import { Kbd } from "@/components/ui/kbd";

export const dynamic = "force-dynamic";

interface Stat {
  label: string;
  value: number;
  sub: string;
  href: string;
  critical?: number;
  accent?: boolean;
}

function StatTile({ stat }: { stat: Stat }) {
  return (
    <Link href={stat.href} className={"stat-tile" + (stat.accent ? " accent" : "")}>
      <div className="stat-top">
        <span className="stat-label">{stat.label}</span>
        <ArrowUp className="stat-go size-3.5" />
      </div>
      <div className="stat-num-row">
        <span className="stat-num">{stat.value}</span>
        <span className="stat-sub">{stat.sub}</span>
      </div>
      <div className="stat-foot">
        {stat.critical ? (
          <span className="stat-chip tone-danger">
            <TriangleAlert className="size-3" />
            {stat.critical} critical
          </span>
        ) : (
          <span className="stat-chip">cleared</span>
        )}
      </div>
    </Link>
  );
}

const QUICK_ACTIONS = [
  { href: "/email/runs", label: "Trigger triage run", hint: "Classify unread mail", icon: Zap, kbd: "T" },
  { href: "/email/drafts", label: "New draft", hint: "Compose an AI-assisted reply", icon: PenLine, kbd: "D" },
  { href: "/reminders", label: "New reminder", hint: "Schedule a one-off or cron", icon: Bell, kbd: "R" },
];

const INTEGRATIONS = [
  { name: "GitHub", desc: "Issues & PR triage", icon: GitBranch },
  { name: "Linear", desc: "Sync tasks & cycles", icon: SquareKanban },
  { name: "Calendar", desc: "Schedule from email", icon: Calendar },
];

export default async function HomePage() {
  let stats: Stat[] = [];
  let apiError: string | null = null;
  try {
    const [emails, drafts, reminders] = await Promise.all([
      getEmails({ category: "critical,needs_reply", status: "open" }),
      getDrafts(),
      getReminders("pending"),
    ]);
    const critical = emails.filter((e) => e.category === "critical").length;
    stats = [
      { label: "Email triage", value: emails.length, sub: "need action", href: "/email", critical },
      { label: "Drafts", value: drafts.filter((d) => d.kind === "reply").length, sub: "pending review", href: "/email/drafts", accent: true },
      { label: "Reminders", value: reminders.length, sub: "pending", href: "/reminders" },
    ];
  } catch (e) {
    apiError = e instanceof Error ? e.message : "API unreachable";
  }

  const hour = new Date().getHours();
  const greet = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  const today = new Date().toLocaleDateString("en-US", { weekday: "long", month: "short", day: "numeric" });

  return (
    <div className="home">
      <div className="home-greet">
        <h1 className="page-title">{greet}</h1>
        <p className="page-sub">Your assistant&apos;s workspace. Integrations land here as they come online.</p>
      </div>
      <div className="home-date mono">{today}</div>

      {apiError && (
        <div className="home-full">
          <Panel>
            <EmptyState icon="TriangleAlert" title="API unreachable" body={apiError} />
          </Panel>
        </div>
      )}

      {/* STATS */}
      <div className="home-stats">
        {!apiError && stats.map((s) => <StatTile key={s.href} stat={s} />)}
      </div>

      {/* ACTIVITY */}
      <div className="home-activity">
        <Panel
          title="Recent activity"
          sub="Latest runs, sends, and reminders"
          actions={
            <Link href="/email/runs" className="flex items-center gap-0.5 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground">
              View runs <ChevronRight className="size-3" />
            </Link>
          }
          noPad
        >
          <EmptyState
            icon="History"
            title="Activity feed — coming soon"
            body="A unified timeline of runs, sends, and fired reminders will live here once it has a source."
          />
        </Panel>
      </div>

      {/* QUICK ACTIONS + INTEGRATIONS (right rail) */}
      <div className="home-quick">
        <Panel title="Quick actions" sub="Also via ⌘K">
          <div className="qa-grid">
            {QUICK_ACTIONS.map((a) => (
              <Link key={a.label} href={a.href} className="qa-card">
                <span className="qa-ic">
                  <a.icon className="size-4" />
                </span>
                <span className="qa-text">
                  <span className="qa-label">{a.label}</span>
                  <span className="qa-hint">{a.hint}</span>
                </span>
                <Kbd>{a.kbd}</Kbd>
              </Link>
            ))}
          </div>
        </Panel>

        <Panel title="Integrations" sub="Connect more sources">
          <div className="integ-list">
            {INTEGRATIONS.map((it) => (
              <div key={it.name} className="integ-row">
                <span className="integ-ic">
                  <it.icon className="size-4" />
                </span>
                <span className="integ-text">
                  <span className="integ-name">{it.name}</span>
                  <span className="integ-desc">{it.desc}</span>
                </span>
                <span className="rounded-full border border-border px-2 py-0.5 text-[11px] font-medium text-faint">Soon</span>
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}
