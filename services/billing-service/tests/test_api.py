import yaml
from fastapi.testclient import TestClient

from app.main import app

c = TestClient(app)


def test_consumer_flow_and_render():
    r = c.post("/consumers", json={"name": "acme", "plan": "pro"})
    assert r.status_code == 201
    key = r.json()["api_key"]
    assert c.post("/consumers", json={"name": "acme"}).status_code == 409
    assert c.post("/consumers", json={"name": "x", "plan": "nope"}).status_code == 422
    assert c.put("/consumers/acme/plan", json={"plan": "enterprise"}).status_code == 200
    cfg = yaml.safe_load(c.get("/kong/config").json()["yaml"])
    acme = cfg["consumers"][0]
    assert acme["keyauth_credentials"][0]["key"] == key
    assert acme["plugins"][0]["config"]["minute"] == 1000
