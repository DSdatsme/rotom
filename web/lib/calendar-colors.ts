const PALETTE = [
  "bg-blue-500/15 text-blue-700 dark:text-blue-300",
  "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
  "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  "bg-fuchsia-500/15 text-fuchsia-700 dark:text-fuchsia-300",
  "bg-cyan-500/15 text-cyan-700 dark:text-cyan-300",
];

/** Deterministic color per account name, so the same account always renders the same color. */
export function colorForAccount(account: string): string {
  let hash = 0;
  for (let i = 0; i < account.length; i++) {
    hash = (hash * 31 + account.charCodeAt(i)) % PALETTE.length;
  }
  return PALETTE[hash];
}
