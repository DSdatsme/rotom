# Generation prompt — dashboard

> Paste into an AI coding agent together with `docs/architecture/PROMPT.md` (it assumes the
> JSON API: bearer auth, `/api/emails*`, `/api/drafts*`, `/api/reminders*`). Also see
> `docs/prompts/frontend.md` and `docs/prompts/design.md` for code/visual conventions.

---

Build a Next.js 16 (App Router) dashboard for a personal AI assistant: triage classified
email, review/send reply drafts (human-in-the-loop), and manage reminders. It talks ONLY to
the documented JSON API.

> **This is Next.js 16, not the version you remember.** `params` and `searchParams` are
> Promises — `await` them. Read `node_modules/next/dist/docs/` before writing routing code.

**Design direction.** Dark mode default (`<html className="dark">`), zinc base palette,
single accent, shadcn new-york on **Base UI** primitives. Geist Sans + Geist Mono via
`next/font/google`; mono for timestamps/ids/countdowns. Comfortable density (gap-6, p-6,
text-sm), lucide icons at h-4 w-4, theme tokens only (`bg-background`, `text-muted-foreground`,
`border-border`), no gradients/glassmorphism. Always design empty/loading/error states.

- **Tailwind v4 `@theme inline` font gotcha:** put the **literal font family name** in the
  `--font-*` token (`--font-sans: "Geist", "Geist Fallback", ...`), not the
  `var(--font-geist-sans)` CSS variable. Inside `@theme inline` the var indirection resolves
  to nothing and text falls back to the system font.

**Base UI render-prop, not `asChild`.** To render a shadcn/Base UI component as another
element (button as a `Link`, dropdown trigger as a `Button`), pass `render={<Link .../>}` —
there is NO `asChild`. Getting this wrong silently renders nested/duplicate elements.

**Data layer.**
- `lib/api.ts` is `import "server-only"`. An `apiFetch<T>(path, init)` helper attaches
  `Authorization: Bearer ${process.env.API_TOKEN}` and throws `Error("API <status> on …")`
  on `!res.ok`. The token must never reach the browser — only server components/actions
  import this. Export typed wrappers; TS interfaces mirror the API JSON exactly.
- `lib/actions.ts` is `"use server"`. Each mutation wraps the API client, calls
  `revalidatePath(...)`, and returns `{ ok: boolean; error?: string }` — never throw across
  the boundary. Send/discard may `redirect()` instead.
- Every data page wraps its fetch in try/catch and renders a destructive `Alert` titled
  "API unreachable" (detail pages may `notFound()`). Do this on EVERY page.

**Pages & components.**
- `app/layout.tsx`: dark html, font variables, `SidebarProvider` + sidebar + main.
- Config-driven sidebar: a `NAV_SECTIONS` array, one section per integration; active item
  via `usePathname()`; menu buttons `render={<Link/>}`.
- **Email list** (`/email`, force-dynamic): filters live in `searchParams`. Apply defaults
  (`category=critical,needs_reply`, `status=open`) ONLY when the URL is untouched — detect
  with an `f` marker: the client filter component sets `f=1` whenever the user changes a
  filter, so `!searchParams.f` ⇒ defaults, else honor the URL verbatim (an explicit empty
  filter must survive). Filter changes `router.replace` a new querystring; the server
  refetches. A bare Reset navigates to `/email`.
- **Overlay-link row/card pattern:** row/card is `relative`; the primary link is
  `after:absolute after:inset-0` so the whole surface is clickable; any nested interactive
  child (checkbox, button) is `relative z-10` to sit above the overlay.
- **Bulk status:** multi-select rows; an action bar appears when ≥1 selected; mark
  done/irrelevant/reopen via a server action then `router.refresh()`; clear selection.
- **Draft editor = the HITL send gate.** A `Textarea` with Save / Send / Discard. Send
  persists edits then POSTs the send action then `redirect("…?sent=1")`. This human click
  is the ONLY way email leaves the system — there is no automated send anywhere.
- **Reminders board:** countdown tiles + an inline add tile + an NL chat bar. The ticking
  `now` is `useState<number|null>(null)`, set in a `useEffect` interval — **null until
  mounted** so SSR/client markup match (no hydration error). Countdowns `font-mono
  tabular-nums`. `datetime-local` is naive; `new Date(value).toISOString()` to send UTC.

**Conventions.** Client components only where interactivity demands; `useTransition` for
pending UI; controlled inputs; `router.refresh()` after mutations.
