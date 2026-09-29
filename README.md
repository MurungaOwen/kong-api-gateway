# kong-api-gateway

API billing system built around Kong (DB-less) as a learning project.
FastAPI services, TypeScript for usage ingest and dashboard.

## Milestone 1: skeleton

    docker compose up --build
    curl localhost:8000/api/quote
    curl localhost:8000/api/echo      # note the X-Forwarded-* and X-Kong headers
    curl localhost:8001/routes        # Admin API view of the loaded config

Roadmap: auth + tiers, metering (TS ingest), Lua plugin, invoices, observability.
