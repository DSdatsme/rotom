# rotom Dashboard — Design Revamp Brief & Per-Page Prompts

> **Purpose:** prompts to feed Claude's design tool to revamp every page of the rotom dashboard.
> Paste the **Master Brief** as the first message of each design session, then paste one **Page Prompt**.
> Attach a screenshot of the current page when you can. Every design must be implementable in the **Fixed Stack** below.

Last updated: 2026-06-14

---

## The problem we're fixing

The dashboard has **no design identity and two clashing visual languages**:

- Most pages use neutral shadcn defaults — gray cards, gray badges, flat tables. Generic.
- `observability`, `logs`, and `runs` drifted into a different **hardcoded "GitHub-dark"** palette (`zinc-900/40`, `bg-[#161b22]`, `zinc-800`, `bg-white/5`).
- The whole theme is pure grayscale (`oklch(… 0 0)`), dark-only, Geist + Geist Mono.

The fix is **not** a costume. It's a single, coherent, high-craft system focused on three things: **speed (snappiness), navigation (effortless), and scannability (information density done right)** — with one confident accent and zero gimmicks.

---

## Fixed stack (state this so the tool doesn't hallucinate)

- **Next.js 16 App Router**, React Server Components. Pages fetch server-side; interactivity/polling lives in `"use client"` components. Keep that split.
- UI primitives are **`@base-ui/react`**, wrapped shadcn-style in `web/components/ui/*` — **NOT Radix**. Do not import Radix.
- **Tailwind v4**; tokens live in `web/app/globals.css` under `@theme inline` + `:root`/`.dark`. **lucide-react** icons. **recharts** for charts.
- Deliver: (a) an updated `globals.css` token palette block, (b) the page in TSX reusing `components/ui/*`, (c) any new shared presentational components (e.g. `Panel`, `StatTile`, `CommandPalette`), (d) **preserve every real data field/label** named in the page prompt.

---

## MASTER BRIEF (paste once per session)

> You are redesigning the dashboard for **rotom**, a personal AI assistant (Gmail triage, AI-drafted replies, reminders, background "runs," observability). One person uses it daily as a control surface. The current UI is generic grayscale shadcn with no identity, and three pages drifted into a separate hardcoded "GitHub-dark" palette. Your job: give it ONE cohesive identity that is **fast, effortless to navigate, and exceptionally crafted** — distinctive through interaction quality and restraint, **not** through a decorative theme. No mascots, no skeuomorphism, no novelty.
>
> **Design values, in priority order:**
> 1. **Snappy.** Everything feels instant. Optimistic UI for mutations, skeleton/streaming for loads, route prefetch, zero layout shift, persistent shell (never a full reload), transitions ≤180ms ease-out with no bounce. Perceived performance is a feature.
> 2. **Effortless navigation.** A **command palette (Cmd/Ctrl-K)** to jump to any page or run any action (trigger triage, new draft, new reminder, search emails). Global keyboard shortcuts. Clear breadcrumbs on detail pages. One predictable layout pattern across every page so the user never relearns.
> 3. **Scannable density.** Tables and lists pack information without clutter — strong typographic hierarchy, aligned numerics, quiet rows that surface the one thing that matters. Comfortable on detail/compose pages; compact on tables/logs/runs.
> 4. **Restraint & reference-grade craft.** A tight neutral ramp, generous whitespace, hairline borders, **deliberate iconography** (consistent lucide weight + size), **pixel-precise alignment**, and a sense that every control sits exactly where it should. Distinctive comes from precision, not decoration.
>
> **Reference products — match this calibre of craft (borrow their judgment, not their brand):**
> - **Linear** — keyboard-first speed, near-monochrome restraint, immaculate empty states and quick micro-interactions, an accent so quiet it's invisible until it means something.
> - **Vercel** — monochrome high-contrast clarity, Geist typography (which this app already uses), generous whitespace, crisp 1px borders, color reserved almost entirely for status.
> - **Datadog** — dense, scannable data UI. Apply its discipline specifically to the **Observability, Logs, and Runs** pages: compact tables, faceted filters, legible time-series, severity color-coding.
>
> **Mode:** Dark-first and dark-only for now (still define `:root`, but `.dark` is canonical).
>
> **Color — neutral-forward, like Vercel/Linear (give me exact oklch tokens):**
> - **Near-monochrome.** Neutrals do almost all the work: a precise dark ramp (background → elevated surface → border → muted text → near-white foreground) with high contrast and crisp hairline borders. Background ≈ `oklch(0.17 0.004 265)`, card ≈ `oklch(0.205 0.005 265)`, border `oklch(1 0 0 / 9%)`, muted text `oklch(0.71 0.008 265)`. A *barely-there* cool tint (Linear-style) or fully pure neutral (Vercel-style) are both acceptable — your call.
> - **Color is reserved for meaning, not decoration** — semantic status only: success = emerald `oklch(0.72 0.16 155)`, warning = amber `oklch(0.80 0.15 75)`, destructive = rose-red `oklch(0.62 0.23 18)`. Always pair status with an icon/label, never color alone.
> - **One restrained accent — YOU choose the exact hue.** Pick a single, confident, low-saturation accent in the Linear spirit (a refined indigo/violet, or a quiet blue) and use it *sparingly*: primary action, active nav, focus ring, the one number that matters. It should be invisible until it's meaningful, and must never compete with the semantic status colors. Ship it as one token so it propagates everywhere.
> - **Email categories get a legible coding:** critical = rose-red, needs_reply = the accent, fyi = cool slate, skip = muted. "Possible injection" = amber danger with a shield motif.
>
> **Typography:** Keep **Geist Sans** for body/UI (it's Vercel's own typeface and already loaded — lean into it). Use a **monospace for all machine data** — IDs, timestamps, token counts, cron strings, account/email addresses, model names, logs (keep Geist Mono). Headings stay in Geist with a tight, confident type scale; avoid **Inter, Roboto, system-ui, Space Grotesk** for any display role. Establish one type scale and hold it on every page.
>
> **Motion — fast and functional only:** 120–180ms ease-out; subtle, purposeful (hover feedback, press states, content fade-in on load, a quiet pulse for genuinely "live" data). No decorative animation, no glow, no bounce. Honor `prefers-reduced-motion`.
>
> **Surfaces:** flat cards with 1px token borders and a soft shadow; minimal elevation. Define ONE reusable `Panel` (header strip + body) used for every chart/table/log container so the whole app shares one container grammar.
>
> **Hard consistency mandate:** everything uses semantic CSS tokens. Replace all hardcoded `zinc-900/40`, `bg-[#161b22]`, `zinc-800`, `bg-white/5`, and the light `bg-blue-100 text-blue-800` pill with tokens so theming is global.
>
> **States are first-class:** design the empty, loading (skeleton), and error state for every list/panel — never a bare "no data" string.
>
> **Accessibility:** WCAG AA contrast on the dark base, visible `ring` focus, full keyboard operability, status conveyed by icon+label not color alone.

---

## Global UX systems to introduce (call out in relevant page prompts)

- **Command palette (Cmd/Ctrl-K):** fuzzy-jump to any page; run quick actions (trigger triage run, new draft, new reminder); search emails by subject/sender. This is the backbone of "effortless navigation."
- **Keyboard shortcuts:** `g` then a key to navigate sections; `j/k` to move through list rows; `e`/`x` for row actions where sensible. Show a `?` shortcuts cheat-sheet.
- **Optimistic mutations:** mark done/irrelevant, discard draft, cancel reminder, send — reflect instantly, reconcile on response, roll back on error.
- **Skeletons + streaming:** every server-fetched page shows a skeleton matching its final layout; no spinners-on-blank.
- **Breadcrumbs** on all detail routes (email detail, draft composer, run detail).

---

## PAGE PROMPT 0 — Global shell & navigation
**Files:** `web/app/layout.tsx`, `web/components/app-sidebar.tsx`
Persistent left sidebar (collapsible via a trigger in a slim top bar) + main content area. Sidebar header: a glyph + **"rotom"** wordmark. Nav is grouped: **Overview** (Home) · **Email** (Inbox triage, Drafts, Runs) · **Reminders** · **Settings** (SOUL Persona) · **Observability** (Usage & Metrics, Logs). Active item is by current path.
Redesign goals: a clean, confident wordmark; active nav marked with the accent + a crisp indicator; refined group labels, icons, and spacing; a well-designed **collapsed rail** state. Add a **top bar with a breadcrumb/title slot, a command-palette trigger (Cmd-K), and a small global status dot** (API connected / live). The sidebar is the home for **future integrations** (GitHub, Linear, Calendar) — design the section pattern so adding one is just another group, no shell rework. Define focus order and keyboard navigation through the nav.

## PAGE PROMPT 1 — Home / Command center
**File:** `web/app/page.tsx`
Today: title "Overview", subtitle "Your assistant's workspace. Integrations land here as they come online.", three link-cards — **Email triage** (`{n} need action`), **Drafts** (`{n} pending review`), **Reminders** (`{n} pending`) — and a destructive "API unreachable" alert state.
Redesign into a fast **command center**: a brief greeting, the three counts as crisp stat tiles (the count is the hero number; click jumps to the section), a compact **recent activity** strip (latest runs/sends), and **quick actions** (trigger triage, new draft, new reminder — also reachable via Cmd-K). Keep all three counts and destinations. Make it skeleton-load instantly. Design the zero/empty and API-error states as first-class. Leave room for future integration tiles.

## PAGE PROMPT 2 — Inbox triage (email list)
**Files:** `web/app/email/page.tsx`, `components/email-table.tsx`, `email-filters.tsx`, `category-badge.tsx`
A filterable table of agent-classified emails. Filters: category, status, account, suspicious, urgency, received date range, triaged date range (default view = `critical,needs_reply` + `open`). Count line "{n} emails". Columns: select-all checkbox, **Account** (mono), **Subject** (link, truncates), **From**, **Category** (badge + a "⚠ possible injection" badge), **Status** (open / done / irrelevant), **Urgency** (—/low/med/high), **Email date**, **Triaged**. Selecting rows reveals a bulk-action bar: **Mark done / Mark irrelevant / Reopen**.
Redesign for **scannability and speed**: apply the category color system; render **urgency as a compact visual scale**, not text; make "possible injection" a clear amber danger treatment; tighten into a dense, legible, hoverable table with `j/k` keyboard row navigation and optimistic bulk actions; turn the bulk bar into a floating action bar that appears without layout shift. Make filters fast to apply and clearly readable when active. Design the "No emails match these filters" empty state and a skeleton.

## PAGE PROMPT 3 — Email detail
**File:** `web/app/email/[id]/page.tsx`
Reading view (max ~3xl), reached from the triage table. Header: subject (h1), "from {sender} · {account} · {date}", a badge row (category, ⚠ injection, "urgency: none/low/medium/high", status), status buttons (mark done/irrelevant/open), and a classification reason line "↳ {reason}". Card **"Email content"** (currently monospace pre-wrapped body/snippet). Card **"Reply draft"**: "AI-drafted reply awaiting your review" or "No pending draft for this email", a regenerate button, and if a draft exists: body preview + "Edit / Send" link + Discard.
Redesign: add a **breadcrumb back to triage**; render the email body as **readable prose** (drop monospace for content); elevate the **classification reasoning** into a tasteful "why rotom flagged this" callout; present the reply draft as a distinct **"rotom drafted a reply"** panel that clearly leads into the composer. Status actions are optimistic. Keep all badges/fields.

## PAGE PROMPT 4 — Drafts list
**File:** `web/app/email/drafts/page.tsx`
Title "Drafts", subtitle "Replies drafted by the agent. Nothing is sent until you say so." A "+ new outreach" action and a "Sent" success alert. Cards per pending draft: title = `Re: {email.subject}` (reply) or outreach subject; a category badge (reply) or an **"Outreach"** pill (currently a light `bg-blue-100` pill that breaks on dark — fix to tokens); description "to {recipient} · {account}"; a 2-line body preview; a Discard button. Empty: "No pending drafts."
Redesign: make these read as **outgoing mail awaiting the human gate** — recipient/subject prominent, reply vs outreach visually distinct, the "nothing sends until you say so" gate felt in the design. Make rows fast to scan and the whole list keyboard-navigable; discard is optimistic. Fix the outreach pill onto tokens. Design the empty + post-send confirmation states and a skeleton.

## PAGE PROMPT 5 — Draft composer (the key workspace)
**Files:** `web/app/email/drafts/[id]/page.tsx`, `components/draft-composer.tsx`
Full-height two-pane workspace. **Left — "Composer Chat":** for replies, the original email up top; a chat thread (user right, rotom left); a textarea ("Tell the agent what to draft… Shift+Enter for newline") + **Generate**. **Right — "Draft Preview":** for outreach, To/Subject inputs; for replies, a "To / Subject" summary; the editable body; an attachments checklist. Footer: **Discard**; an unlabeled **"Sent with rotom" footer toggle** (Switch, explained via tooltip only); **Save**, **Save to Gmail**, **Send** (Send disabled when body empty / outreach has no recipient).
Redesign: make this the **fastest, clearest workspace in the app** — chat as live collaboration, the draft as a tangible letter, instant feedback on generate. Make the **three distinct commit actions** unmistakable (Save = local · Save to Gmail = Gmail drafts · Send = actually sends), with Send carrying the most visual weight and a clear human-gate moment. Give the footer toggle a discoverable affordance (keep tooltip, make its meaning legible). Design generating / sending / saved / error states, and keep zero layout shift as the draft updates. A breadcrumb back to Drafts.

## PAGE PROMPT 6 — Reminders
**Files:** `web/app/reminders/page.tsx`, `components/reminder-board.tsx`, `reminder-chat-bar.tsx`
Title "Reminders", subtitle "Fired to your Telegram chat. Add with the + tile or describe one below." A grid of **countdown tiles**: reminder text, a cancel (X), a large monospace countdown (`Dd HH:MM:SS` / "due now" / "—"), the absolute fire time, and a recurrence-cron badge. A dashed **"+" tile** opens an inline form (text, datetime-local, repeat-as-cron-or-NL). A **sticky bottom chat bar**: natural-language input ("remind me to call mom tomorrow at 3pm") → a proposal card (⏰ confirmation + time + repeats) with **Confirm / Discard**, plus "you confirm before anything is scheduled."
Redesign: the **live countdowns are the hero** — make them tick crisply and let near-due reminders read as more urgent (subtle, via the warning token — not decoration). Clarify recurring vs one-time at a glance. Make the NL chat bar a delightful, fast command line with a clear confirm-gate; cancel/confirm are optimistic. Design the empty state, the add-tile expanded state, and a skeleton.

## PAGE PROMPT 7 — SOUL Persona
**Files:** `web/app/soul/page.tsx`, `soul-editor.tsx`
rotom's identity/style document. Title "SOUL Persona", subtitle "Define your background, tone, and provide writing samples. Rotom uses this to mimic your style perfectly." Currently one large monospace textarea + a Save button (Save / Saving / Saved states + error).
Redesign: make this feel **meaningful and purposeful**, not a raw config blob — frame it as "this shapes every reply rotom writes." Add light structural scaffolding / section hints / example prompts to guide what to write, a comfortable long-form editor with good line length and rhythm, and a satisfying, fast save confirmation (autosave-feel or clear Saved state). Keep it a single editable document (backend stores free text). Restrained and refined — no theme flourishes.

## PAGE PROMPT 8 — Observability (Usage & Metrics)
**Files:** `web/app/observability/page.tsx`, `components/tokens-chart.tsx`
Title "Observability", subtitle "Token usage across all models (Last 14 Days)". A recharts **"Tokens Over Time (stacked by model)"** chart, then a usage table: **Date** (mono), **Purpose** (pill `{purpose} #{run_id}` or italic "adhoc"), **Model** (mono), **Input**, **Output**, **Avg Latency** (right-aligned). Empty: "No usage data recorded yet." **This page hardcodes `zinc-900/40` and `bg-[#161b22]` — move it onto tokens.**
Redesign into a proper, scannable metrics surface: add **KPI summary tiles** (total tokens, total input/output, avg latency, # runs) above the chart; style the recharts chart in the token palette with a restrained series scheme; present the table inside the reusable `Panel` with aligned numerics and clear hierarchy. Design empty + skeleton states.

## PAGE PROMPT 9 — Logs Explorer
**Files:** `web/app/observability/logs/page.tsx`, `components/logs-explorer.tsx`, `logs-panel.tsx`
Title "Logs Explorer", subtitle "Structured application logs with faceted search and live-tail". A filter bar: text search, **level chips** (DEBUG/INFO/WARNING/ERROR, color-coded), a `kind` filter, a time-range segmented control (15m/1h/24h/7d/All), and a **Live / Tail-off** toggle (quiet pulse when live). Below: a scrolling log panel (level, kind, run id, timestamp, message) with "load older" pagination and live-prepend.
Redesign into a **refined, fast log viewer**: level colors via semantic tokens (error=rose, warning=amber, info=accent, debug=muted), tidy monospace rows with clear run/kind tagging, a **sticky filter bar** that's quick to operate, live-tail as a calm "live" state (subtle, not flashy), and smooth incremental loading with no scroll jank. **Move all hardcoded zinc/blue to tokens.** Design loading + empty-results states.

## PAGE PROMPT 10 — Runs list
**Files:** `web/app/email/runs/page.tsx`, `components/runs-list.tsx`
Title "Recent Runs", subtitle "Background tasks and triage logs", plus a **Trigger run** button. **Source facet pills** (all / scheduler / manual / chat / inngest). Each run row: a **status spine bar** (emerald=success, accent/blue-pulse=running, amber=interrupted, rose=failed), the run **kind**, a mono **source** badge, an optional parent "↳ #id", a "live" indicator when running, a summary line, and a relative timestamp. Polls every 4s while any run is running. Empty: "No runs recorded yet."
Redesign into a clean **activity timeline**: status reads instantly via the spine + an icon (not color alone), running rows show a calm live indicator, the source facet filter is fast and obviously active when set, and parent/child + relative time are quietly legible. Keep the polling-driven live updates with no layout shift. Design empty + all-clear states and a skeleton.

## PAGE PROMPT 11 — Run detail
**Files:** `web/app/email/runs/[id]/page.tsx`, `components/run-detail-live.tsx`
A trace view for one run. Back arrow + kind (h1); a parent breadcrumb when nested (`← {parent.kind} #id / {kind}`). A **stats header** (6 cells): Status (icon+color, calm live indicator when running), Source, Started, **Duration** (ticks live while running), In Tokens, Out Tokens, and a full-width Summary. A **Model Usage** table (Model / In / Out / Avg Latency). An error block when failed. A **"View steps in Inngest →"** external link. A **Sub-runs** list (status dot, kind, source pill, #id). An **Execution Logs** console (live while running). Polls every 4s while running. **Hardcodes `zinc-900/40` / `bg-[#161b22]` — move to tokens.**
Redesign into a polished **run/trace inspector**: stats as crisp KPI tiles, the live duration as a quiet ticking timer, the sub-run list as a small tree, the logs reusing the same console grammar as page 9, and the Inngest link styled as a clear external pivot. Keep the breadcrumb, every field, and the live polling behavior. No layout shift as live data updates.

---

## How to use these prompts (workflow)

1. Open a Claude design session, paste **Fixed Stack** + **Master Brief** + **Global UX systems**.
2. Paste the page prompt for the page you're working on; attach a current screenshot.
3. Iterate on tokens first (so all pages stay coherent), then layout, then states.
4. Bring the output back to the repo as `globals.css` token updates + TSX using `components/ui/*`.

**Accent decision:** delegated to the design tool within the neutral-forward guardrails above (Linear-spirit, low-saturation, status-distinct). Whatever it picks lives as one token — review it on the tokens pass before building pages, and it propagates everywhere.
