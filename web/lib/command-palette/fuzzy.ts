/** Subsequence score: contiguous matches rank highest; -1 if not a subsequence. */
export function fuzzyScore(query: string, text: string): number {
  const q = query.toLowerCase().trim();
  const t = text.toLowerCase();
  if (!q) return 0.0001;
  if (t.includes(q)) return 100 - t.indexOf(q);
  let ti = 0,
    score = 0,
    streak = 0;
  for (const c of q) {
    let found = false;
    while (ti < t.length) {
      if (t[ti] === c) {
        streak += 1;
        score += 1 + streak;
        ti++;
        found = true;
        break;
      }
      ti++;
      streak = 0;
    }
    if (!found) return -1;
  }
  return score;
}

export interface PalettePage {
  id: string;
  label: string;
  group: string;
  href: string;
  icon?: string;
}
export interface PaletteAction {
  id: string;
  label: string;
  icon?: string;
  hint?: string;
  kbd?: string;
}
export interface PaletteRow {
  id: string;
  label: string;
  type: "page" | "action";
  group?: string;
  href?: string;
  hint?: string;
  kbd?: string;
  icon?: string;
}
export interface PaletteSection {
  header: string;
  rows: PaletteRow[];
}

export function rankPalette(
  query: string,
  { pages, actions }: { pages: PalettePage[]; actions: PaletteAction[] },
): PaletteSection[] {
  const out: PaletteSection[] = [];

  const actHits = actions
    .map((a) => ({ a, s: fuzzyScore(query, a.label) }))
    .filter((x) => x.s > -1)
    .sort((x, y) => y.s - x.s)
    .map(
      ({ a }): PaletteRow => ({
        id: a.id,
        label: a.label,
        type: "action",
        hint: a.hint,
        kbd: a.kbd,
        icon: a.icon,
      }),
    );

  const pageHits = pages
    .map((p) => ({ p, s: Math.max(fuzzyScore(query, p.label), fuzzyScore(query, p.group) - 5) }))
    .filter((x) => x.s > -1)
    .sort((x, y) => y.s - x.s)
    .map(
      ({ p }): PaletteRow => ({
        id: p.id,
        label: p.label,
        type: "page",
        group: p.group,
        href: p.href,
        icon: p.icon,
      }),
    );

  if (actHits.length) out.push({ header: "Actions", rows: actHits });
  if (pageHits.length) out.push({ header: "Jump to", rows: pageHits });
  return out;
}
