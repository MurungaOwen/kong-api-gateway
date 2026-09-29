import os
import sqlite3

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .kong_config import dump
from .plans import PLANS
from .store import Store

app = FastAPI(title="billing-service")
store = Store(os.getenv("DB_PATH", ":memory:"))
KONG_ADMIN_URL = os.getenv("KONG_ADMIN_URL", "http://kong:8001")


class NewConsumer(BaseModel):
    name: str
    plan: str = "free"


class PlanChange(BaseModel):
    plan: str


def _check_plan(plan):
    if plan not in PLANS:
        raise HTTPException(422, f"unknown plan; choose from {sorted(PLANS)}")


@app.get("/plans")
def plans():
    return list(PLANS.values())


@app.post("/consumers", status_code=201)
def create_consumer(body: NewConsumer):
    _check_plan(body.plan)
    try:
        return store.create(body.name, body.plan)
    except sqlite3.IntegrityError:
        raise HTTPException(409, "consumer exists")


@app.get("/consumers")
def consumers():
    return store.list()


@app.put("/consumers/{name}/plan")
def change_plan(name: str, body: PlanChange):
    _check_plan(body.plan)
    if not store.set_plan(name, body.plan):
        raise HTTPException(404, "no such consumer")
    return {"name": name, "plan": body.plan}


@app.get("/kong/config")
def kong_config():
    return {"yaml": dump(store.list())}


@app.post("/kong/sync")
def kong_sync():
    """Push generated config to Kong's DB-less reload endpoint (POST /config)."""
    r = httpx.post(
        f"{KONG_ADMIN_URL}/config",
        files={"config": ("kong.yml", dump(store.list()), "application/yaml")},
        timeout=10,
    )
    if r.status_code >= 300:
        raise HTTPException(502, r.text)
    return {"synced": True}
