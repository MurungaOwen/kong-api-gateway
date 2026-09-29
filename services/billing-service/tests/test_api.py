import yaml
from fastapi.testclient import TestClient

from app import settings
from app.main import app

c = TestClient(app)


def _cfg():
    return yaml.safe_load(c.get("/kong/config").json()["yaml"])


def _route(cfg, name):
    return next(r for s in cfg["services"] for r in s.get("routes", []) if r["name"] == name)


def _plugin(route, name):
    return next(p for p in route["plugins"] if p["name"] == name)


def _consumer(cfg, name):
    return next(x for x in cfg["consumers"] if x["username"] == name)


PLAN = {"monthly_price_cents": 900, "monthly_included": 5000, "overage_per_1k_cents": 100,
        "per_minute": 30, "endpoints": ["quote"]}


def test_consumer_flow_and_render():
    r = c.post("/consumers", json={"name": "acme", "plan": "pro"})
    assert r.status_code == 201
    key = r.json()["keys"][0]["api_key"]
    assert c.post("/consumers", json={"name": "acme"}).status_code == 409
    assert c.post("/consumers", json={"name": "x", "plan": "nope"}).status_code == 422
    assert c.post("/consumers", json={"name": "bad name!"}).status_code == 422
    assert c.put("/consumers/acme/plan", json={"plan": "enterprise"}).status_code == 200
    assert c.get("/consumers/ghost").status_code == 404

    cfg = _cfg()
    acme = _consumer(cfg, "acme")
    assert acme["keyauth_credentials"] == [{"key": key}]
    assert acme["acls"] == [{"group": "enterprise"}]
    assert acme["plugins"][0]["config"] == {"minute": 1000, "policy": "local", "limit_by": "consumer"}
    assert _consumer(cfg, "dashboard-admin")["jwt_secrets"][0]["secret"] == settings.JWT_SECRET


def test_routes_are_metered_and_gated_by_plan():
    cfg = _cfg()
    names = [p["name"] for p in _route(cfg, "route-quote")["plugins"]]
    assert names == ["key-auth", "acl", "request-transformer", "http-log", "billing-meter"]
    assert _route(cfg, "billing-route")["plugins"][0]["name"] == "jwt"
    # report costs 5 units and is NOT in the free plan
    report = _route(cfg, "route-report")
    assert _plugin(report, "billing-meter")["config"]["units"] == 5
    assert "free" not in _plugin(report, "acl")["config"]["allow"]
    assert "pro" in _plugin(report, "acl")["config"]["allow"]
    assert "free" in _plugin(_route(cfg, "route-quote"), "acl")["config"]["allow"]
    # http-log must NOT be global, or dashboard traffic would be billed as usage
    assert [p["name"] for p in cfg["plugins"]] == ["prometheus"]
    assert cfg["plugins"][0]["config"]["status_code_metrics"] is True
    assert cfg["upstreams"][0]["name"] == "product-api"
    assert cfg["upstreams"][0]["healthchecks"]["active"]["http_path"] == "/health"


def test_key_lifecycle():
    c.post("/consumers", json={"name": "keys", "plan": "free"})
    k2 = c.post("/consumers/keys/keys", json={"label": "ci"}).json()
    assert k2["label"] == "ci" and k2["api_key"]
    assert len(_consumer(_cfg(), "keys")["keyauth_credentials"]) == 2
    first = c.get("/consumers/keys").json()["keys"][0]["id"]
    assert c.delete(f"/consumers/keys/keys/{first}").status_code == 204  # rotate: old key revoked
    assert c.delete(f"/consumers/keys/keys/{first}").status_code == 404
    assert [k["api_key"] for k in c.get("/consumers/keys").json()["keys"]] == [k2["api_key"]]
    assert _consumer(_cfg(), "keys")["keyauth_credentials"] == [{"key": k2["api_key"]}]
    assert c.post("/consumers/ghost/keys", json={}).status_code == 404


def test_plan_management_limits_and_access():
    assert c.post("/plans", json={"name": "starter", **PLAN}).status_code == 201
    assert c.post("/plans", json={"name": "starter", **PLAN}).status_code == 409
    bad = c.post("/plans", json={"name": "ghosty", **PLAN, "endpoints": ["nope"]})
    assert bad.status_code == 422
    c.post("/consumers", json={"name": "plancust", "plan": "starter"})

    body = {**PLAN, "per_minute": 45, "per_second": 5, "per_day": 0, "endpoints": ["quote", "report"]}
    updated = c.put("/plans/starter", json=body).json()
    assert updated["per_day"] is None and updated["endpoints"] == ["quote", "report"]  # 0 = unlimited
    cfg = _cfg()
    assert _consumer(cfg, "plancust")["plugins"][0]["config"]["minute"] == 45   # limits follow the plan
    assert _consumer(cfg, "plancust")["plugins"][0]["config"]["second"] == 5
    assert "starter" in _plugin(_route(cfg, "route-report"), "acl")["config"]["allow"]  # access follows too

    assert c.delete("/plans/starter").status_code == 409  # still in use
    assert c.delete("/consumers/plancust").status_code == 204
    assert "plancust" not in [x["username"] for x in _cfg()["consumers"]]
    assert c.delete("/plans/starter").status_code == 204
    assert c.delete("/plans/starter").status_code == 404
    assert c.put("/plans/ghost", json=PLAN).status_code == 404


def test_unlimited_plan_gets_no_rate_limit_plugin():
    c.post("/plans", json={"name": "open", "monthly_price_cents": 0, "monthly_included": 1,
                           "overage_per_1k_cents": 0, "endpoints": ["quote"]})
    c.post("/consumers", json={"name": "free4all", "plan": "open"})
    assert "plugins" not in _consumer(_cfg(), "free4all")


def test_endpoint_catalog():
    body = {"path": "/api/translate", "units": 3, "description": "translate text"}
    assert c.post("/endpoints", json={"name": "translate", **body}).status_code == 201
    assert c.post("/endpoints", json={"name": "translate", **body}).status_code == 409
    assert c.post("/endpoints", json={"name": "dupe", **body}).status_code == 409  # same path
    assert c.post("/endpoints", json={"name": "evil", "path": "/billing/x", "units": 1}).status_code == 422
    assert c.post("/endpoints", json={"name": "zero", "path": "/api/zero", "units": 0}).status_code == 422

    cfg = _cfg()
    svc = next(s for s in cfg["services"] if s["name"] == "endpoint-translate")
    assert (svc["host"], svc["path"]) == ("product-api", "/translate")   # /api prefix stripped for the backend
    assert _plugin(svc["routes"][0], "billing-meter")["config"]["units"] == 3
    assert _plugin(svc["routes"][0], "acl")["config"]["allow"] == ["__no_plan__"]  # no plan includes it yet

    c.put("/endpoints/translate", json={**body, "units": 4})
    assert next(e for e in c.get("/endpoints").json() if e["name"] == "translate")["units"] == 4
    c.post("/plans", json={"name": "poly", **PLAN, "endpoints": ["translate"]})
    assert c.delete("/endpoints/translate").status_code == 204
    assert all("translate" not in p["endpoints"] for p in c.get("/plans").json())  # removed from plans too
    assert c.delete("/endpoints/translate").status_code == 404
    assert c.put("/endpoints/ghost", json=body).status_code == 404


def test_invoice_endpoint(monkeypatch):
    import httpx

    c.post("/consumers", json={"name": "bill", "plan": "pro"})

    class Resp:
        def raise_for_status(self): pass
        def json(self): return {"total": 101_000, "calls": 30, "by_route": {"r": 101_000}}

    monkeypatch.setattr(httpx, "get", lambda *a, **k: Resp())
    inv = c.get("/invoices/bill?month=2026-09").json()
    assert inv["usage"]["overage_units"] == 1_000
    assert inv["total_cents"] == 4_900 + 50
    assert c.get("/invoices/bill?month=nope").status_code == 422
    assert c.get("/invoices/ghost").status_code == 404


def test_upstream_management_and_routing():
    up = {"targets": ["orders:9000", "orders-b:9000"], "algorithm": "least-connections", "health_path": "/healthz", "health_interval": 10}
    assert c.post("/upstreams", json={"name": "orders", **up}).status_code == 201
    assert c.post("/upstreams", json={"name": "orders", **up}).status_code == 409
    assert c.post("/upstreams", json={"name": "bad", **up, "targets": ["no-port"]}).status_code == 422
    assert c.post("/upstreams", json={"name": "bad", **up, "targets": []}).status_code == 422
    assert c.post("/upstreams", json={"name": "bad", **up, "algorithm": "random"}).status_code == 422

    # an endpoint served by the new backend, with an explicit backend path
    ep = {"name": "orders-list", "path": "/api/orders", "units": 2, "upstream": "orders", "upstream_path": "/v1/orders"}
    assert c.post("/endpoints", json=ep).status_code == 201
    assert c.post("/endpoints", json={**ep, "name": "x", "path": "/api/x", "upstream": "ghost"}).status_code == 422

    cfg = _cfg()
    u = next(x for x in cfg["upstreams"] if x["name"] == "orders")
    assert u["algorithm"] == "least-connections" and [t["target"] for t in u["targets"]] == ["orders:9000", "orders-b:9000"]
    assert u["healthchecks"]["active"]["http_path"] == "/healthz"
    svc = next(s for s in cfg["services"] if s["name"] == "endpoint-orders-list")
    assert (svc["host"], svc["path"]) == ("orders", "/v1/orders")

    assert c.delete("/upstreams/orders").status_code == 409          # still serves an endpoint
    c.delete("/endpoints/orders-list")
    assert c.put("/upstreams/orders", json={**up, "targets": ["orders:9001"]}).json()["targets"] == ["orders:9001"]
    assert c.delete("/upstreams/orders").status_code == 204
    assert c.delete("/upstreams/orders").status_code == 404
