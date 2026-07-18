<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version (Next.js 16, React 19) has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

# rotom dashboard — agent notes

The review surface for rotom. Server components fetch from the FastAPI backend through
`lib/api.ts` (the bearer `API_TOKEN` stays server-side and never reaches the browser).
The **Send** button is the human-in-the-loop gate — the only place email actually sends.

## Stack & conventions

- **Next.js 16 App Router**, React 19, **Base UI** (not Radix/shadcn — note Base UI props
  like `nativeButton` and `useRender`), Tailwind, and a hand-written design system in
  `app/globals.css`.
- Styling is split: Tailwind utility classes for layout in JSX **and** semantic component
  classes defined in `app/globals.css` (e.g. `.rundetail`, `.rstat-grid`, `.tbl`). When a
  page "won't take the width" or similar, check `globals.css` for a `max-width` on the
  page's root class before touching the JSX.
- The app shell (`components/app-shell.tsx`) centers every page in
  `mx-auto max-w-[1440px] px-6`. Page root classes should generally **not** add their own
  narrower `max-width` unless the content genuinely reads better narrow.
- Data is fetched in server components / route handlers; `"use client"` components poll via
  `/api/*-proxy` routes. Keep the token server-side.
- `cd web && npm run lint` before considering web work done.

## Gotcha: turbopack dev server serves stale CSS

`next dev` (turbopack) **sometimes stops recompiling** — its file watcher gets stuck and it
keeps serving a cached CSS chunk. Symptom: you edit `globals.css` (or a component), the
**source is correct**, but the browser's computed styles are unchanged and a `touch` of the
file does nothing. Verify by fetching the served chunk directly:

```bash
# chunk name is in the page HTML under /_next/static/chunks/...css
curl -s http://localhost:3001/<that-chunk>.css | grep -A4 '.rundetail'
```

If the served CSS still shows the old rule, the dev server is stale. **Fix: restart it**
(and clear the cache if it persists):

```bash
# kill the stuck `next dev`, then:
rm -rf web/.next        # clears the stale turbopack cache
cd web && npm run dev
```

Don't keep editing source chasing a fix that's already correct — confirm against the
*served* CSS first.
