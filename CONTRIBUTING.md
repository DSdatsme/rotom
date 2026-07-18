# Contributing to rotom

Thanks for your interest! rotom is a single-user personal assistant; see
[`AGENTS.md`](AGENTS.md) for the architecture and the invariants to preserve.

## Dev setup

```bash
cp .env.example .env      # fill in tokens/keys
make dev                  # API + Inngest + dashboard together
```

- `make api` — API only (FastAPI + Telegram bot + scheduler, one process)
- `make web` — dashboard only

## Before you open a PR

```bash
cd api && uv run pytest    # tests fake Gmail + the LLM — no network, no real LLM calls
cd web && npm run lint     # eslint
cd web && npm run build    # type-checked production build
```

- Branch off `master`; don't commit straight to it.
- Keep changes focused and match the surrounding style. Prefer simple,
  human-readable code.
- **Don't make real LLM calls** in tests — the token budget is limited and the
  suite is designed to run offline.

## Reporting issues

Bugs and ideas → [open an issue](https://github.com/DSdatsme/rotom/issues).
Security problems → see [`SECURITY.md`](SECURITY.md) (report privately, not as an issue).
