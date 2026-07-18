<!-- Keep it short. Delete sections that don't apply. -->

## What & why

<!-- What does this change, and why? -->

## Checklist

- [ ] `cd api && uv run pytest` passes
- [ ] `cd web && npm run lint` and `npm run build` pass (if web touched)
- [ ] No secrets/PII added; email content still treated as untrusted
- [ ] Preserves the core invariants in `AGENTS.md` (agent never sends autonomously, etc.)
