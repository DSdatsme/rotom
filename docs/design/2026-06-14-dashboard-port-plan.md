# Dashboard Redesign — Port Plan

> **Status:** Plan only — no code yet. Review and approve before implementation.
> **Date:** 2026-06-14
> **Inputs:** design brief (`docs/design/2026-06-14-dashboard-design-brief.md`) + Claude Design mockups (`docs/design/mockups/`).
> **Target:** `web/` (Next.js 16 App Router, RSC, React 19, Tailwind v4, `@base-ui/react`, lucide-react, recharts).

This plan maps the build-free React prototype in `docs/design/mockups/` onto the real Next.js dashboard. It covers the architecture translation, a token-by-token CSS migration map, a mockup-file → `web/` file mapping, a per-page checklist, the build sequence, and the open decisions that need a call before/while building.

---

## 1. The core translation problem

The mockup and the real app are **architecturally different**, so this is not a copy-paste:

| Concern | Mockup (`docs/design/mockups/`) | Real app (`web/`) |
|---|---|---|
| Rendering | One client SPA, Babel-in-browser | RSC pages (`export const dynamic = "force-dynamic"`) + client islands |
| Routing | `route` state in `app.jsx`, no URLs | File-based App Router, real URLs, `[id]` params |
| Data | `window.ROTOM` mock globals | `web/lib/api.ts` typed fetch → FastAPI, bearer token |
| Mutations | Local `useState` + `setTimeout` fakes | Server actions (`"use server"`) |
| Live data | `setInterval` faking polls/tails | `/app/api/*-proxy/route.ts` handlers polled by client components |
| Components | Functions attached to `window` | RSC + `"use client"` modules, shadcn primitives on `@base-ui` |
| Styling | One hand-written CSS file (semantic classes) | Tailwind v4 utilities + shadcn tokens in `globals.css` |
| Icons | Inlined Lucide SVG paths in `Icon` | `lucide-react` |

**What we keep from the mockup:** the visual design (tokens, spacing, type, the violet accent), the markup structure of each screen, and the interaction logic (keyboard nav, filters, countdowns, command palette fuzzy match).

**What we keep from the real app:** all data fetching (`lib/api.ts`), all existing server actions, URL-based routing and filters, the `/api/*-proxy` polling handlers, recharts, and the shadcn primitives that already exist.

**The work per screen** is therefore: take the mockup's JSX + CSS, split it into an RSC page (data fetch) + client island(s) (interactivity), rewire field names to the real types, and call the existing server actions instead of the mockup's fakes.

---

## 2. Design-token migration (`web/app/globals.css`)

The app is already forced into dark mode (`<html className="dark">`), and the mockup is dark-only — so we rewrite the `.dark` block to the mockup palette and leave `:root` (light) as a fallback we don't ship. The mockup's tokens are richer and denser than the current shadcn grayscale defaults.

### 2a. Map mockup tokens → shadcn token names

The trick: remap onto the **shadcn semantic names** wherever they correspond, so every existing shadcn primitive (Button, Card, Table, Checkbox, DropdownMenu…) inherits the new look for free. Then **add** the extra mockup-only tokens.

| Mockup token | Value | Maps to shadcn var | Notes |
|---|---|---|---|
| `--bg` | `oklch(0.17 .005 265)` | `--background` | page canvas |
| `--bg-1` | `oklch(0.188 …)` | `--sidebar`, topbar rail | |
| `--card` | `oklch(0.205 …)` | `--card`, `--popover` | |
| `--card-2` | `oklch(0.235 …)` | `--accent`, `--secondary` | hover layer (shadcn `accent` = hover bg) |
| `--card-3` | `oklch(0.275 …)` | (new `--card-3`) | active-hover / tooltip bg |
| `--border` | `oklch(1 0 0 / .09)` | `--border`, `--sidebar-border` | |
| `--border-strong` | `oklch(1 0 0 / .15)` | `--input` | |
| `--fg` | `oklch(0.965 …)` | `--foreground`, `--card-foreground` | |
| `--fg-2` | `oklch(0.86 …)` | (new `--fg-2`) | secondary text |
| `--muted` | `oklch(0.71 …)` | `--muted-foreground` | |
| `--faint` | `oklch(0.56 …)` | (new `--faint`) | group labels, hints |
| `--accent` (violet) | `oklch(0.62 0.13 274)` | `--primary` + new `--brand` | see 2b |
| `--accent-fg` | `oklch(0.99 0 0)` | `--primary-foreground` | |
| `--success` | `oklch(0.72 .16 155)` | (new) | semantic |
| `--warning` | `oklch(0.80 .15 75)` | (new) | semantic |
| `--danger` | `oklch(0.645 .21 20)` | `--destructive` | |
| `--slate` | `oklch(0.66 .035 245)` | (new) | FYI / second chart series |
| `--radius` | `11px` | `--radius` (set to `0.7rem`) | up from `0.625rem` |

> **Naming note:** the mockup calls its brand colour `--accent`, but shadcn's `--accent` means "subtle hover background." To avoid collisions, in the real app the **brand violet becomes `--primary` (+ a `--brand` alias)** and shadcn's `--accent` stays the neutral hover layer (`--card-2`). All mockup CSS that reads `var(--accent)` gets renamed to `var(--brand)` during the port.

### 2b. The violet accent

In the mockup the brand violet drives: active-nav indicator/icon, links, focus ring, and `btn-primary` fills (Generate, Send, Trigger run). Mapping:

- `--primary: oklch(0.62 0.13 274)` / `--primary-foreground: oklch(0.99 0 0)` → shadcn primary buttons become the violet CTA (matches mockup `btn-primary`).
- `--ring: <accent-line>` so focus rings are violet.
- Add `--brand`, `--brand-soft` (`color-mix … 18%`), `--brand-line` (`color-mix … 55%`) for nav indicators, link text, glows.
- `btn-default` (neutral card button) maps to shadcn `secondary`/`outline` variant.

The brief delegated the exact accent to the design tool; it chose **Violet `oklch(0.62 0.13 274)`**. Confirm we're keeping it (see Decisions §6).

### 2c. New tokens to add to `@theme inline` + `:root`/`.dark`

So Tailwind utilities resolve (`text-success`, `bg-brand-soft`, etc.) and raw `var()` works in ported CSS:

```
--brand, --brand-soft, --brand-line
--fg-2, --faint
--success, --warning, --slate
--card-3
--dur: 150ms;  --ease: cubic-bezier(0.25,0.6,0.25,1);
--side-w: 234px;
/* density (compact, baked) */ --fs: 13px; --pad: 15px; --gap: 14px; --nav-h: 31px; --row-h: 38px;
```

### 2d. Density & type

- Bake **compact** as the single density (base `font-size: 13px`, the compact spacing scale). Drop the mockup's runtime density switch.
- Fonts already correct: Geist + Geist Mono loaded in `layout.tsx`, literal names already in `@theme inline`. Add a `.mono` helper (`font-feature-settings: "tnum" 1`).
- Scrollbar, `::selection`, and `:focus-visible` ring styles port directly into `@layer base`.

### 2e. CSS strategy — hybrid, **utilities-first** (locked)

The mockup is ~1,500 lines of semantic-class CSS (`.panel`, `.nav-item`, `.run-row`, `.cmdk`, `.chart-*`…). We do **not** port that monolith. Priority is readable, easy-to-manage code, so the order of preference is:

1. **shadcn primitives** (restyled via tokens) for standard widgets — Button, Card, Table, Checkbox, Input, Textarea, Switch, DropdownMenu, Tooltip, Skeleton, Badge.
2. **Tailwind utilities co-located in the component JSX** for everything else — layout, spacing, one-off styling. This is the default; styles live next to the markup that uses them.
3. **A small set of `@layer components` classes** *only* for genuinely complex, repeated bespoke patterns where inline utilities would hurt readability: command-palette rows, run/log console rows, the sidebar active-indicator, urgency scale. Keep this set short and named clearly.

Rule of thumb: if a widget's styling fits comfortably as utilities in one component, keep it there; promote to a `@layer components` class only when the same complex pattern repeats or the utility string becomes unreadable. No giant global semantic stylesheet.

---

## 3. Shared primitives map

| Mockup (`components.jsx` / `shell.jsx`) | Real-app target |
|---|---|
| `Icon` (inlined SVG) | **Drop** — use `lucide-react` directly. Map names (mostly 1:1; e.g. `file-text`→`FileText`, `alarm-clock`→`AlarmClock`, `corner-down-left`→`CornerDownLeft`). |
| `Panel` (header strip + body) | New `components/ui/panel.tsx` (thin wrapper; or restyle shadcn `Card`). Used on most pages. |
| `Button` (variant/size/icon) | Existing `components/ui/button.tsx` — add `primary` (violet) + `ghost` + `sm/md` parity; map `btn-default`→`secondary`. |
| `Badge` (tone) | Existing `components/ui/badge.tsx` — add tone variants (brand/success/warning/danger/slate/muted). Reuse for `CategoryBadge`. |
| `StatusDot` (tone, pulse) | New small `components/ui/status-dot.tsx`. |
| `Kbd` | New `components/ui/kbd.tsx`. |
| `Skeleton` | Existing `components/ui/skeleton.tsx`. |
| `EmptyState` | New `components/ui/empty-state.tsx`. |
| `ErrorBanner` | New `components/ui/error-banner.tsx` (or reuse shadcn `Alert`). |
| `Toaster` + toast queue | New `components/ui/toaster.tsx` + a client context/provider mounted in `layout.tsx`. (Lightweight port; no new dep — alternative: add `sonner`. See §6.) |

---

## 4. File mapping (mockup → `web/`)

| Mockup file | Real-app file(s) | Action |
|---|---|---|
| `data.js` | — | Reference only. Field names get remapped to `lib/api.ts` types (see §5). **Not** ported. |
| `components.jsx` | `components/ui/*` | Port primitives per §3. |
| `shell.jsx` | `app/layout.tsx`, `components/app-sidebar.tsx`, new `components/top-bar.tsx` | Rebuild shell. |
| `palette.jsx` | new `components/command-palette.tsx` | Port self-contained fuzzy palette. |
| `app.jsx` | `app/layout.tsx` + per-page wiring | Routing/state replaced by App Router; keep keyboard-shortcut + toast logic at shell level. |
| `tweaks-panel.jsx` | — | **Drop** (design-exploration tool; bake choices into tokens). |
| `home.jsx` | `app/page.tsx` (+ client islands) | Port. |
| `email.jsx` (`InboxTriage`) | `app/email/page.tsx`, `components/email-table.tsx`, `components/email-filters.tsx` | Restyle existing + add keyboard nav, facet dropdowns, urgency scale, bulk bar. |
| `email.jsx` (`EmailDetail`) | `app/email/[id]/page.tsx` (+ `email-status-buttons`, `regenerate-draft-button`, `discard-draft-button`) | Restyle existing. |
| `drafts.jsx` (`DraftsList`) | `app/email/drafts/page.tsx`, `components/create-draft-button.tsx`, `components/discard-draft-button.tsx`, new draft-list client | Port cards + gate strip + keyboard nav. |
| `drafts.jsx` (`DraftComposer`) | `app/email/drafts/[id]/page.tsx`, `components/draft-composer.tsx` | Restyle existing composer (it already has chat+preview+actions). |
| `reminders.jsx` | `app/reminders/page.tsx`, `components/reminder-board.tsx`, `components/reminder-chat-bar.tsx` | Restyle existing; use real `parseReminder` for the chat bar. |
| `soul.jsx` | `app/soul/page.tsx`, `app/soul/soul-editor.tsx` | Restyle existing; add hints aside + counts. |
| `observability.jsx` | `app/observability/page.tsx`, `components/tokens-chart.tsx` | Add KPI tiles; **keep recharts**, restyle to mockup look (don't port the hand-rolled SVG). |
| `logs.jsx` | `app/observability/logs/page.tsx`, `components/logs-explorer.tsx`, `components/logs-panel.tsx` | Restyle existing; keep real polling + `logger`/`extra` columns. |
| `runs.jsx` (`RunsList`) | `app/email/runs/page.tsx`, `components/runs-list.tsx` | Restyle existing; keep polling + source facets. |
| `runs.jsx` (`RunDetail`) | `app/email/runs/[id]/page.tsx`, `components/run-detail-live.tsx` | Restyle existing; keep `LogsPanel` reuse. |

---

## 5. Field-name remap (mockup → real `lib/api.ts` types)

The mockup invents its own field names. Every ported screen must translate to the real types. The important deltas:

**Email** (`EmailItem` / `EmailDetail`):
- `cat` → `category` · `injection` → `suspicious` · `from`/`fromName` → **`sender`** (real has a single string, no separate display name — render `sender` as-is, or parse `Name <addr>` if present) · `urgency` string `none/low/medium/high` → **`urgency` number `0/1/2/3`** · `dateEmail`+`timeEmail` → format `received_at` · `triaged` → relative-format `created_at` · `reason`, `subject`, `account`, `status` match. Detail drafts live in `EmailDetail.drafts[]`.

**Draft** (`DraftItem`):
- `type` → `kind` (`reply`/`outreach`) · `to` → `to_addr` · `chat[{role,text}]` → `messages[{role,content,created_at}]` · `footer` → `rotom_footer_default` · `recipientName` → **derive** from `to_addr`/`email.sender` (no such field) · `updated` → relative `created_at` · attachments already `{key,label}` · linked email in `email`.

**Reminder** (`ReminderItem` / `ReminderProposal`):
- `fireAt` → `fire_at` / `next_fire_at` · `cron` → `recurrence_cron` · **drop `channel`** (that's ntfy v2, not in the API). Chat bar uses real `parseReminder()` → `{text, fire_at, recurrence_cron, confirmation}` instead of the mockup's client-side `parseNL`.

**Run** (`RunLog` / `RunDetail`):
- status `failed` → **`failure`** (real `RunStatus = running|success|failure|interrupted`) · `relSec`/`_start` → `started_at` · `durMs` → `finished_at − started_at` · `parent` → `parent_run_id` + `parent` ref · `subs` → `children[]` · `models[{model,in,out,lat}]` → `metrics[{model,input_tokens,output_tokens,avg_latency_ms}]` · `tokIn`/`tokOut` → sum of `metrics` · `steps` → parse `logs` (JSONL) via `LogsPanel` · inngest link → `external_url`.

**Usage** (`UsageAggregation`): `date`→`day` · `runId`→`run_id` · `input`→`input_tokens` · `output`→`output_tokens` · `latency`→`avg_latency_ms` · `purpose` matches.

**Logs** (`LogEntry`): `lvl`→`level` · `runId`→`run_id` · `ts`,`kind`,`msg` match · real adds `logger` + `extra` (JSON, expandable) — **keep** these (mockup omits them).

---

## 6. Decisions (resolved)

1. **Accent** — ✅ **Keep Violet `oklch(0.62 0.13 274)`** (the design tool's choice). One token to swap later if needed.
2. **CSS strategy** — ✅ **Hybrid, utilities-first** (§2e). Priority is readable, manageable code: shadcn primitives → Tailwind utilities in components → a short list of `@layer components` classes only for complex repeated widgets. No global semantic-CSS monolith.
3. **Sidebar** — ✅ **Keep the shadcn `Sidebar` and restyle it.** It already owns the mobile drawer, collapse state, provider, and a11y — a custom rebuild would re-own all of that. The mockup's look (violet active-indicator bar, badge pills, collapsed tooltips) is mostly CSS layered onto `SidebarMenuButton`. Keep `NAV_SECTIONS` + `SidebarProvider`/`SidebarTrigger`. Ship **only the "bar" indicator** (drop the dot/fill variants — they were Tweaks-panel exploration).
4. **Toaster** — ✅ Lightweight port (no new dep), mounted as a provider in `layout.tsx`.
5. **Command palette email search** — ✅ **Defer.** No backend search param, and we're not building backend for this. Cmd-K v1 = **pages + quick actions only**; the "Emails" section is omitted (or shows a quiet "search coming soon" hint). Revisit if/when a backend `q` param lands.
6. **Home "Recent activity"** — ✅ **Placeholder panel** ("Activity feed — coming soon"), styled like a real Panel with an empty state. No activity endpoint, no derivation; build it when there's a source.
7. **Nav badge counts** (inbox/drafts/reminders) — ✅ **Omit badges in v1.** No count endpoints, and we're not fetching all lists in `layout.tsx` just for badges. Nav items render without the count pill; revisit when a cheap count source exists.
8. **Breadcrumb** — detail-page crumbs need the entity title (email subject, draft subject, run id). Resolve via a client `TopBar` reading `usePathname` + a route→label map, with detail pages supplying their title through a context/slot. (Default approach; not blocking.)

**Backend stance (locked):** this redesign builds **no new backend**. Where the UI wants data that has no endpoint (activity feed, nav counts, Cmd-K email search), ship a **placeholder / "coming soon"** treatment or omit the element — never stub the API.

---

## 7. Build sequence (each phase is a reviewable checkpoint)

**Phase 0 — Tokens & primitives.** Rewrite `globals.css` token layer (§2); add the new tokens to `@theme inline`; port shared primitives (§3); add bespoke component CSS under `@layer components`. *Reviewable:* Storybook-free smoke — existing pages should still render, now in the new palette/density.

**Phase 1 — Shell.** `layout.tsx` + restyled shadcn sidebar (bar indicator, no badges v1) + `top-bar.tsx` (breadcrumb, API-status pill, Cmd-K trigger) + command palette (**pages + quick actions only**, no email search) + toaster + global keyboard shortcuts (⌘K, ⌘\, `g`-then-key, `t`). *Reviewable:* navigate every existing route inside the new shell.

**Phase 2 — Home** (`app/page.tsx`): greeting, 3 stat tiles (counts), **recent-activity placeholder panel** ("coming soon" empty state — no endpoint), quick actions, integrations list.

**Phase 3 — Inbox triage + Email detail.** Facet filter bar (URL-driven, restyled), urgency scale, suspicious toggle, category/status/injection badges, j/k/x/e keyboard nav, bulk action bar; detail header/badges/status-actions/reason/quarantine/reply-draft panel.

**Phase 4 — Drafts list + Composer.** Draft cards (rail by category/outreach, gate badges, j/k nav, sent alert, gate strip); composer two-pane chat+preview, typing indicator, original-email card, commit footer bar, footer toggle, attachments.

**Phase 5 — Reminders.** Countdown tiles (live 1s ticker, urgency-by-time colour), inline add tile, NL chat bar → real `parseReminder` → propose/confirm.

**Phase 6 — Runs list + Run detail.** Status spine + live polling + source facet pills + trigger; detail stat grid, error panel, model-usage table, inngest link, sub-runs tree, execution console (via `LogsPanel`).

**Phase 7 — Observability (Usage).** KPI tiles + recharts stacked tokens-over-time (restyled) + usage log table.

**Phase 8 — Logs Explorer.** Search + level chips + kind select + time-range segment + live-tail toggle + log rows (+ `logger`/`extra` expand) + load-older pagination.

**Phase 9 — SOUL Persona.** Editor + autosave-feel debounce (via `updateSoul`) + word/sample counts + hints aside + banner.

Phases 2–9 are independent and each touches ~1 route, so they're individually PR-sized and reviewable. Phase 0 and Phase 1 are the shared foundation and must land first.

---

## 8. Out of scope (explicitly dropped)

- The **Tweaks panel** (`tweaks-panel.jsx`) — design-exploration only; choices baked into tokens.
- The mockup's **mock data** (`data.js`) and **fake async** (`setTimeout` generate/send/poll) — replaced by real API + actions.
- Reminder **`channel`** field and any ntfy/Telegram channel UI — that's the separately-spec'd ntfy v2 work, not this redesign.
- Light mode — app is dark-only; `:root` light tokens stay as an unused fallback.
- No backend/API changes are required by this plan except the *optional* Cmd-K email-search param (Decision §6.5) and any optional count endpoints (§6.7).
