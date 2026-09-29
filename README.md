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

## Milestone 3: metering

A global `http-log` plugin (batched via `queue`) ships every request log to the
TypeScript `usage-ingest` service. Billable = identified consumer and status < 400
(so 401/429/5xx are free). After some authenticated calls (batches flush within ~2s):

    curl localhost:8100/usage                      # consumers with usage
    curl 'localhost:8100/usage/acme?month=2026-09' # totals by route

Usage is in-memory for now; durable storage arrives with invoicing.

## Milestone 4: custom Lua plugin

`kong/plugins/billing-meter` (mounted into Kong, enabled via `KONG_PLUGINS`) runs in the
`log` phase, builds a billing event (consumer, plan from the `plan:*` consumer tag,
route, weighted `units`, latency) and ships it to `usage-ingest` `/events` from a
zero-delay timer (the log phase forbids cosockets). Pure logic lives in `event.lua`:

    lua5.1 kong/plugins/billing-meter/spec/event_spec.lua

Compare both metering paths for a consumer:

    curl localhost:8100/compare/acme

Trade-off to observe: `http-log` is config-only and batched; the plugin can carry
billing semantics (plan, units) but sends one request per call for now (a `kong.tools.queue`
batch is the obvious next step) and is code you own and must keep compatible with Kong upgrades.

Roadmap: auth + tiers, metering (TS ingest), Lua plugin, invoices, observability.
