# kong-api-gateway

API billing system built around Kong (DB-less) as a learning project.
FastAPI services, TypeScript for usage ingest and dashboard.

## Milestone 1: skeleton

    docker compose up --build
    curl localhost:8000/api/quote
    curl localhost:8000/api/echo      # note the X-Forwarded-* and X-Kong headers
    curl localhost:8001/routes        # Admin API view of the loaded config

## Milestone 2: auth + tiers

    curl -X POST localhost:8090/consumers -H 'content-type: application/json' -d '{"name":"acme","plan":"free"}'
    curl -X POST localhost:8090/kong/sync          # renders kong.yml from billing data, reloads Kong
    curl localhost:8000/api/quote                  # 401 without a key
    curl localhost:8000/api/quote -H 'apikey: <key>'   # note X-RateLimit-* response headers

Kong OSS lacks consumer-group rate limiting (Enterprise), so the plan's limit is
attached as a per-consumer `rate-limiting` plugin. DB-less trade-off: config changes
mean a full reload via `POST /config`.

Roadmap: auth + tiers, metering (TS ingest), Lua plugin, invoices, observability.
