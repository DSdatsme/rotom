.PHONY: help dev api web

help:
	@echo "make dev   start API + Inngest + dashboard (Ctrl-C stops all)"
	@echo "make api   start API only"
	@echo "make web   start dashboard only"

# Start everything (Ctrl-C stops all)
dev:
	@trap 'kill 0' INT; \
	(cd api && uv run python -m app.main) & \
	npx --yes inngest-cli@latest dev -u http://localhost:8000/api/inngest & \
	(cd web && npm run dev) & \
	wait

api:
	cd api && uv run python -m app.main

web:
	cd web && npm run dev
