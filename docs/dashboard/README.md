# Dashboard

Next.js 16 App Router UI for triaging email, sending reply drafts, and managing
reminders. Talks only to the FastAPI JSON API; the bearer token never reaches the
browser. Lives in `web/`.

## How it works

- **Next.js 16, App Router.** `params` and `searchParams` are **Promises** — every page
  `await`s them. Pages that read live data are `export const dynamic = "force-dynamic"`
  (no caching; the API is the source of truth).
- **shadcn on Base UI primitives** (new-york style, dark mode). Base UI does NOT use
  Radix's `asChild` — to render a component as a different element (e.g. a button as a
  `Link`) you pass `render={<Link href={...} />}`. This is the single biggest gotcha.
- **Server-only API client** (`lib/api.ts`, `import "server-only"`): `apiFetch` attaches
  `Authorization: Bearer ${API_TOKEN}` and throws on `!res.ok`. TypeScript interfaces
  (`EmailItem`, `DraftItem`, `ReminderItem`, …) mirror the API JSON exactly. Server
  components call these directly; the token stays on the server.
- **Server actions** (`lib/actions.ts`, `"use server"`): mutations wrap the API client,
  `revalidatePath` the affected route, and return `{ ok, error }` — they never throw
  across the boundary. Client components call them inside `useTransition` and then
  `router.refresh()` to repaint. `sendDraft`/`discardDraft` `redirect()` instead.
- **Every page handles "API unreachable"**: the `try/catch` around the fetch renders a
  destructive `Alert` (or `notFound()` on detail pages) instead of crashing.

## Layout & navigation

`app/layout.tsx` sets `dark`, the Geist Sans/Mono font variables, and wraps everything in
`SidebarProvider` + `AppSidebar`. The sidebar (`components/app-sidebar.tsx`) is config-
driven: `NAV_SECTIONS` is a list of `{label, items}` — **one section per integration**, so
adding GitHub/Linear later is one array entry. Active item via `usePathname()`.

## Email triage

- `app/email/page.tsx` reads filters from `searchParams`. The `f=1` URL marker means "user
  touched the filters": defaults (`critical,needs_reply` + `open`) apply ONLY when the URL
  is untouched (`!sp.f`), so an explicit empty filter isn't overwritten by defaults.
- `EmailFilters` (client) keeps every selection in the URL. Each change builds a new
  querystring, sets `f=1`, and `router.replace`s — the server refetches. Multi-selects are
  comma-joined; Reset navigates to bare `/email`.
- `EmailTable` (client) is the **overlay-link row pattern**: the row is `relative`, the
  subject link is `after:absolute after:inset-0` (fills the row), and the checkbox cell is
  `relative z-10` so it stays clickable above the overlay. Multi-select drives bulk status
  actions (done / irrelevant / reopen) via `setEmailsStatus` + `router.refresh()`.
- **Injection flag**: emails quarantined by the triage guardrail carry `suspicious: true`;
  the table row + detail page show a destructive `⚠ possible injection` badge, and a
  tri-state `suspicious` filter (All / Suspicious only / Hide) browses them (they're
  `category=skip`, so otherwise hidden from the action-required default). See
  [`docs/guardrails/`](../guardrails/).

## Drafts & SOUL

Draft cards (`app/email/drafts/page.tsx`) use the same overlay-link pattern. The editor
(`components/draft-composer.tsx`) is a two-pane conversational UI where a human iterates with
an LLM, reviews, and **Sends** — this click is the only path email leaves the system. 
`sendDraft` persists last edits then POSTs send, then redirects to `?sent=1` for the confirmation Alert. 
Non-pending drafts render read-only. An unlabeled **"Sent with rotom" switch** (base-ui `Switch` +
tooltip) sits by Discard; it initializes from the draft's `rotom_footer_default` (global config) and
its value rides the send/save request as `rotom_footer` — not persisted. See [`../draft-composer/`](../draft-composer/).

The LLM persona is configured via a dashboard at `app/soul/page.tsx`.

## Reminders

`components/reminder-board.tsx` renders countdown tiles. The ticking clock is **null until
mounted** (`useState<number|null>(null)`, set in `useEffect`) so SSR and first client render
match — no hydration mismatch. Countdowns use `font-mono tabular-nums`. The `ReminderChatBar`
parses NL into a proposal the user confirms (see `docs/reminders/`).

## Key files

`app/layout.tsx` · `app/page.tsx` · `app/email/page.tsx` · `app/email/[id]/page.tsx` ·
`app/email/drafts/page.tsx` · `app/email/drafts/[id]/page.tsx` · `app/reminders/page.tsx` ·
`components/app-sidebar.tsx` · `components/email-filters.tsx` · `components/email-table.tsx` ·
`components/draft-composer.tsx` · `components/reminder-board.tsx` · `lib/api.ts` · `lib/actions.ts`
