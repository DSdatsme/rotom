# Prompt — rotom visual language

> Paste into an AI coding agent (or design tool) to generate UI that matches this product.

---

Generate UI in rotom's visual language: a calm, dense, dark developer-tool aesthetic.

**Foundation**
- **Dark mode by default** (`<html className="dark">`). No light-mode toggle unless asked.
- **Zinc base palette** with a **single accent** (the primary). Don't introduce extra hues
  beyond status colors.
- **shadcn/ui, new-york style**, built on **Base UI** primitives.
- **Geist Sans** for everything; **Geist Mono** for anything machine-ish — timestamps, ids,
  account names, countdowns, cron strings, code. Numerics that update use `tabular-nums`.

**Density & spacing**
- Comfortable, not airy: `gap-6` / `p-6` page-level, `text-sm` body, `text-2xl
  font-semibold tracking-tight` page titles with a `text-sm text-muted-foreground` subtitle.
- Content max-widths on detail/form pages (`mx-auto max-w-3xl`).

**Components**
- **Cards** for tiles and grouped content; `relative` + `transition-colors
  hover:bg-accent/50` when the whole card is a link (overlay-link pattern).
- **lucide-react** icons at `h-4 w-4` (smaller `h-3 w-3` inline in badges/labels).
- **Status via `Badge` variants** — `outline` for neutral/secondary state, color only to
  signal urgency/category. Keep the badge text terse and lowercase-ish.
- **Tables** for lists with many columns; **card grids** (`sm:grid-cols-2 lg:grid-cols-3
  xl:grid-cols-4`) for tiles.

**Tokens only — never raw colors.** `bg-background`, `text-foreground`,
`text-muted-foreground`, `bg-card`, `border-border`, `bg-accent`, `text-destructive`,
`text-primary`. This keeps theming centralized and dark/light correct.

**No** gradients, glassmorphism, drop-shadows-as-decoration, or animated flourishes. Motion
is limited to hover color transitions and `Loader2 animate-spin` on pending actions.

**Always design the non-happy states.** Every list has an empty state (a muted one-liner);
every async surface has a loading state (`Skeleton` or a spinner on the action); every fetch
has an error state (`Alert variant="destructive"`, e.g. titled "API unreachable").
Destructive confirms (delete/discard with consequences) use `AlertDialog`, not a bare button.

**Tailwind v4 `@theme inline` font gotcha:** the `--font-*` tokens must hold the **literal**
family name (`"Geist", "Geist Fallback", ...`), not a `var(--font-geist-sans)` reference —
the var indirection resolves to empty inside `@theme inline` and you silently get the system
font.
