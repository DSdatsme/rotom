# Prompt — frontend code conventions

> Paste into an AI coding agent before writing/editing frontend code in this codebase.
> Pair with `docs/prompts/design.md` for the visual language.

---

Write frontend code in this codebase's style. Stack: Next.js 16 App Router, TypeScript,
shadcn on Base UI, Tailwind v4.

> **This is Next.js 16 — not the version in your training data.** Read the relevant guide
> in `node_modules/next/dist/docs/` before writing routing/data code. Heed deprecations.

**Server vs client.**
- Default to **server components**. They fetch data directly via the server-only API client
  (`lib/api.ts`) — never `fetch` the API from the browser.
- `params` and `searchParams` are **Promises** — `await` them.
- Pages reading live data: `export const dynamic = "force-dynamic"`.
- Add `"use client"` ONLY where interactivity demands it (state, effects, event handlers).

**Data access.**
- `lib/api.ts` is `import "server-only"`. `apiFetch<T>(path, init)` attaches the bearer
  token from `process.env.API_TOKEN` and **throws** on `!res.ok` (`API <status> on <path>`).
  Export small typed wrappers per endpoint. The token never reaches the browser.
- TypeScript interfaces mirror the API JSON **exactly** (field names, nullability, unions).
- Every data-fetching page wraps the call in try/catch and renders an "API unreachable"
  `Alert` (detail pages may `notFound()`), so the API being down degrades gracefully.

**Mutations.**
- Live in `lib/actions.ts` (`"use server"`). Each wraps the API client, calls
  `revalidatePath(...)`, and returns `{ ok: boolean; error?: string }` — **never throw
  across the action boundary**. Some flows `redirect()` instead (e.g. after send).
- Client callers run actions inside `useTransition` (drive `disabled` + a `Loader2
  animate-spin` from `isPending`), then `router.refresh()` to repaint server data.

**Components.**
- **Base UI render prop, NOT `asChild`**: render a component as another element with
  `render={<Link href={...} />}`. There is no `asChild` here.
- **Overlay-link pattern**: clickable row/card is `relative`; the primary `Link` is
  `after:absolute after:inset-0`; nested interactive children are `relative z-10`.
- Controlled inputs (`value` + `onChange`). Numeric/time displays use `tabular-nums`; ids,
  timestamps, cron strings use `font-mono`.
- Client time tickers start `null` until a `useEffect` mount, then update — so SSR and the
  first client render match (no hydration mismatch).
- Config-drive repetitive UI (e.g. sidebar nav as a `NAV_SECTIONS` array).
