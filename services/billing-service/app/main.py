import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from . import invoice, settings
from .kong_config import dump
from .plans import Endpoint, Plan, Upstream
from .store import PlanInUse, Store, UnknownEndpoint, UnknownUpstream, UpstreamInUse

app = FastAPI(title="billing-service")
store = Store(settings.DB_PATH)
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _month(month):
    month = month or datetime.now(timezone.utc).strftime("%Y-%m")
    if not MONTH_RE.match(month):
        raise HTTPException(422, "month must look like 2026-09")
    return month


def sync_kong():
    """Persist kong.yml (so a Kong restart keeps every consumer) and hot-reload Kong.

    DB-less Kong has no per-entity API: a change means replacing the whole config.
    """
    yaml_text = dump(store.list(), store.plans(), store.endpoints(), store.upstreams(), settings.JWT_SECRET)
    if settings.KONG_CONFIG_PATH:
        Path(settings.KONG_CONFIG_PATH).write_text(yaml_text)
    r = httpx.post(
        f"{settings.KONG_ADMIN_URL}/config",
        files={"config": ("kong.yml", yaml_text, "application/yaml")},
        timeout=10,
    )
    if r.status_code >= 300:
        raise HTTPException(502, r.text)


def _auto_sync():
    if settings.AUTO_SYNC:
        sync_kong()


@app.get("/health")
def health():
    return {"status": "ok"}


NAME = r"^[a-zA-Z0-9_-]{1,40}$"  # the name ends up in URLs, YAML and Kong usernames


class NewConsumer(BaseModel):
    name: str = Field(pattern=NAME)
    plan: str = "free"


class PlanChange(BaseModel):
    plan: str


class PlanFields(BaseModel):
    monthly_price_cents: int = Field(ge=0)
    monthly_included: int = Field(ge=0)
    overage_per_1k_cents: int = Field(ge=0)
    # Kong rate limits per subscriber; null/0 = unlimited for that window.
    per_second: int | None = Field(default=None, ge=0, le=1_000_000)
    per_minute: int | None = Field(default=None, ge=0, le=1_000_000)
    per_hour: int | None = Field(default=None, ge=0, le=100_000_000)
    per_day: int | None = Field(default=None, ge=0, le=1_000_000_000)
    endpoints: list[str] = []  # names of catalog endpoints this plan may call


class NewPlan(PlanFields):
    name: str = Field(pattern=NAME)


class EndpointFields(BaseModel):
    path: str = Field(pattern=r"^/api/[a-zA-Z0-9_/-]{1,80}$")
    units: int = Field(ge=1, le=1_000_000)
    description: str = Field(default="", max_length=200)
    upstream: str = "product-api"
    upstream_path: str = Field(default="", pattern=r"^(/[a-zA-Z0-9_./-]{0,120})?$")  # empty = derive from path


class NewEndpoint(EndpointFields):
    name: str = Field(pattern=NAME)


class UpstreamFields(BaseModel):
    targets: list[Annotated[str, Field(pattern=r"^[a-zA-Z0-9.-]{1,120}:\d{1,5}$")]] = Field(min_length=1, max_length=50)
    algorithm: Literal["round-robin", "least-connections"] = "round-robin"
    health_path: str = Field(default="/health", pattern=r"^/[a-zA-Z0-9_./-]{0,120}$")
    health_interval: int = Field(default=5, ge=1, le=300)


class NewUpstream(UpstreamFields):
    name: str = Field(pattern=NAME)


class NewKey(BaseModel):
    label: str = Field(default="generated", max_length=60)


def _check_plan(plan):
    plans = store.plans()
    if plan not in plans:
        raise HTTPException(422, f"unknown plan; choose from {sorted(plans)}")


def _plan(name, body):
    fields = body.model_dump(exclude={"name"})
    fields["endpoints"] = tuple(dict.fromkeys(fields["endpoints"]))
    for k in ("per_second", "per_minute", "per_hour", "per_day"):
        fields[k] = fields[k] or None  # 0 means unlimited
    return Plan(name=name, **fields)


def _save_plan(plan):
    try:
        store.upsert_plan(plan)
    except UnknownEndpoint as e:
        raise HTTPException(422, f"unknown endpoint {e}; known: {sorted(store.endpoints())}")


@app.get("/plans")
def plans():
    return [p.dict() for p in store.plans().values()]


@app.post("/plans", status_code=201)
def create_plan(body: NewPlan):
    if body.name in store.plans():
        raise HTTPException(409, "plan exists")
    plan = _plan(body.name, body)
    _save_plan(plan)
    _auto_sync()  # a new plan changes ACLs on the routes it includes
    return plan.dict()


@app.put("/plans/{name}")
def update_plan(name: str, body: PlanFields):
    """Price/allowance changes hit invoices immediately; limits and endpoint access need a Kong reload."""
    if name not in store.plans():
        raise HTTPException(404, "no such plan")
    plan = _plan(name, body)
    _save_plan(plan)
    _auto_sync()
    return plan.dict()


@app.delete("/plans/{name}", status_code=204)
def delete_plan(name: str):
    try:
        if not store.delete_plan(name):
            raise HTTPException(404, "no such plan")
    except PlanInUse:
        raise HTTPException(409, "plan still has subscribers; move them first")
    _auto_sync()


@app.get("/upstreams")
def upstreams():
    return [u.dict() for u in store.upstreams().values()]


@app.post("/upstreams", status_code=201)
def create_upstream(body: NewUpstream):
    if body.name in store.upstreams():
        raise HTTPException(409, "upstream exists")
    return _save_upstream(Upstream(body.name, tuple(dict.fromkeys(body.targets)), body.algorithm, body.health_path, body.health_interval))


@app.put("/upstreams/{name}")
def update_upstream(name: str, body: UpstreamFields):
    if name not in store.upstreams():
        raise HTTPException(404, "no such upstream")
    return _save_upstream(Upstream(name, tuple(dict.fromkeys(body.targets)), body.algorithm, body.health_path, body.health_interval))


def _save_upstream(u):
    store.upsert_upstream(u)
    _auto_sync()
    return u.dict()


@app.delete("/upstreams/{name}", status_code=204)
def delete_upstream(name: str):
    try:
        if not store.delete_upstream(name):
            raise HTTPException(404, "no such upstream")
    except UpstreamInUse:
        raise HTTPException(409, "upstream still serves endpoints; move or delete them first")
    _auto_sync()


@app.get("/endpoints")
def endpoints():
    return [e.dict() for e in store.endpoints().values()]


@app.post("/endpoints", status_code=201)
def create_endpoint(body: NewEndpoint):
    if body.name in store.endpoints():
        raise HTTPException(409, "endpoint exists")
    return _save_endpoint(Endpoint(body.name, body.path, body.units, body.description, body.upstream, body.upstream_path))


@app.put("/endpoints/{name}")
def update_endpoint(name: str, body: EndpointFields):
    if name not in store.endpoints():
        raise HTTPException(404, "no such endpoint")
    return _save_endpoint(Endpoint(name, body.path, body.units, body.description, body.upstream, body.upstream_path))


def _save_endpoint(ep):
    try:
        store.upsert_endpoint(ep)
    except sqlite3.IntegrityError:
        raise HTTPException(409, f"path {ep.path} is already used by another endpoint")
    except UnknownUpstream:
        raise HTTPException(422, f"unknown upstream {ep.upstream}; known: {sorted(store.upstreams())}")
    _auto_sync()
    return ep.dict()


@app.delete("/endpoints/{name}", status_code=204)
def delete_endpoint(name: str):
    if not store.delete_endpoint(name):
        raise HTTPException(404, "no such endpoint")
    _auto_sync()


@app.post("/consumers", status_code=201)
def create_consumer(body: NewConsumer):
    _check_plan(body.plan)
    try:
        created = store.create(body.name, body.plan)
    except sqlite3.IntegrityError:
        raise HTTPException(409, "consumer exists")
    _auto_sync()
    return created


@app.get("/consumers")
def consumers():
    return store.list()


@app.get("/consumers/{name}")
def consumer(name: str):
    c = store.get(name)
    if not c:
        raise HTTPException(404, "no such consumer")
    return c


@app.put("/consumers/{name}/plan")
def change_plan(name: str, body: PlanChange):
    _check_plan(body.plan)
    if not store.set_plan(name, body.plan):
        raise HTTPException(404, "no such consumer")
    _auto_sync()
    return {"name": name, "plan": body.plan}


@app.delete("/consumers/{name}", status_code=204)
def delete_consumer(name: str):
    """Removes the subscriber and their keys from Kong. Recorded usage is kept."""
    if not store.delete(name):
        raise HTTPException(404, "no such consumer")
    _auto_sync()


@app.post("/consumers/{name}/keys", status_code=201)
def create_key(name: str, body: NewKey = NewKey()):
    key = store.add_key(name, body.label)
    if not key:
        raise HTTPException(404, "no such consumer")
    _auto_sync()
    return key


@app.delete("/consumers/{name}/keys/{key_id}", status_code=204)
def revoke_key(name: str, key_id: int):
    if not store.revoke_key(name, key_id):
        raise HTTPException(404, "no such active key")
    _auto_sync()


@app.get("/invoices/{name}")
def get_invoice(name: str, month: str | None = None):
    month = _month(month)
    c = store.get(name)
    if not c:
        raise HTTPException(404, "no such consumer")
    try:
        r = httpx.get(f"{settings.USAGE_INGEST_URL}/usage/{name}", params={"month": month}, timeout=10)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(502, f"usage-ingest unavailable: {e}")
    u = r.json()
    return invoice.compute(name, store.plans()[c["plan"]], month, u["total"], u["calls"], u["by_route"])


@app.get("/kong/health")
def kong_health():
    """Live target health per upstream, straight from Kong's Admin API."""
    out = {}
    for name in store.upstreams():
        try:
            r = httpx.get(f"{settings.KONG_ADMIN_URL}/upstreams/{name}/health", timeout=5)
            r.raise_for_status()
            out[name] = [
                {"target": t["target"], "health": t["health"], "address": t.get("data", {}).get("addresses", [])}
                for t in r.json().get("data", [])
            ]
        except httpx.HTTPError:
            out[name] = None  # Kong unreachable or has not loaded this upstream yet
    return out


@app.get("/kong/config")
def kong_config():
    return {"yaml": dump(store.list(), store.plans(), store.endpoints(), store.upstreams(), settings.JWT_SECRET)}


@app.post("/kong/sync")
def kong_sync():
    sync_kong()
    return {"synced": True}
