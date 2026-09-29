import json
import secrets
import sqlite3
import threading
from datetime import datetime, timezone

from .plans import DEFAULT_ENDPOINTS, DEFAULT_PLANS, DEFAULT_UPSTREAMS, Endpoint, Plan, Upstream

PLAN_COLS = (
    "name", "monthly_price_cents", "monthly_included", "overage_per_1k_cents",
    "per_second", "per_minute", "per_hour", "per_day",
)


class PlanInUse(Exception):
    pass


class UnknownEndpoint(Exception):
    pass


class UnknownUpstream(Exception):
    pass


class UpstreamInUse(Exception):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    """SQLite store: plans, consumers (subscribers) and their API keys."""

    def __init__(self, path=":memory:"):
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.RLock()
        with self._db:
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS plans (
                    name TEXT PRIMARY KEY,
                    monthly_price_cents INTEGER NOT NULL, monthly_included INTEGER NOT NULL,
                    overage_per_1k_cents INTEGER NOT NULL,
                    per_second INTEGER, per_minute INTEGER, per_hour INTEGER, per_day INTEGER);
                CREATE TABLE IF NOT EXISTS upstreams (
                    name TEXT PRIMARY KEY, targets TEXT NOT NULL, algorithm TEXT NOT NULL,
                    health_path TEXT NOT NULL, health_interval INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS endpoints (
                    name TEXT PRIMARY KEY, path TEXT NOT NULL UNIQUE, units INTEGER NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    upstream TEXT NOT NULL REFERENCES upstreams(name), upstream_path TEXT NOT NULL DEFAULT '');
                CREATE TABLE IF NOT EXISTS plan_endpoints (
                    plan TEXT NOT NULL REFERENCES plans(name), endpoint TEXT NOT NULL REFERENCES endpoints(name),
                    PRIMARY KEY (plan, endpoint));
                CREATE TABLE IF NOT EXISTS consumers (
                    name TEXT PRIMARY KEY, plan TEXT NOT NULL REFERENCES plans(name), created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, consumer TEXT NOT NULL REFERENCES consumers(name),
                    api_key TEXT NOT NULL UNIQUE, label TEXT NOT NULL, created_at TEXT NOT NULL,
                    revoked INTEGER NOT NULL DEFAULT 0);
                """
            )
            if not self._db.execute("SELECT 1 FROM plans LIMIT 1").fetchone():
                for u in DEFAULT_UPSTREAMS:
                    self._write_upstream(u)
                for e in DEFAULT_ENDPOINTS:
                    self._write_endpoint(e)
                for p in DEFAULT_PLANS:
                    self._write_plan(p)

    # ---- upstreams ---------------------------------------------------------
    def upstreams(self):
        rows = self._db.execute("SELECT name, targets, algorithm, health_path, health_interval FROM upstreams ORDER BY name")
        return {r[0]: Upstream(r[0], tuple(json.loads(r[1])), r[2], r[3], r[4]) for r in rows}

    def _write_upstream(self, u):
        self._db.execute(
            "INSERT INTO upstreams VALUES (?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET "
            "targets=excluded.targets, algorithm=excluded.algorithm, "
            "health_path=excluded.health_path, health_interval=excluded.health_interval",
            (u.name, json.dumps(list(u.targets)), u.algorithm, u.health_path, u.health_interval),
        )

    def upsert_upstream(self, u):
        with self._lock, self._db:
            self._write_upstream(u)

    def delete_upstream(self, name):
        with self._lock, self._db:
            if self._db.execute("SELECT 1 FROM endpoints WHERE upstream=?", (name,)).fetchone():
                raise UpstreamInUse(name)
            return self._db.execute("DELETE FROM upstreams WHERE name=?", (name,)).rowcount > 0

    # ---- endpoints ---------------------------------------------------------
    def endpoints(self):
        rows = self._db.execute(
            "SELECT name, path, units, description, upstream, upstream_path FROM endpoints ORDER BY path"
        )
        return {r[0]: Endpoint(*r) for r in rows}

    def _write_endpoint(self, e):
        if not self._db.execute("SELECT 1 FROM upstreams WHERE name=?", (e.upstream,)).fetchone():
            raise UnknownUpstream(e.upstream)
        self._db.execute(
            "INSERT INTO endpoints VALUES (?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET "
            "path=excluded.path, units=excluded.units, description=excluded.description, "
            "upstream=excluded.upstream, upstream_path=excluded.upstream_path",
            (e.name, e.path, e.units, e.description, e.upstream, e.upstream_path),
        )

    def upsert_endpoint(self, e):
        """Raises sqlite3.IntegrityError if the path is already used, UnknownUpstream if the backend isn't registered."""
        with self._lock, self._db:
            self._write_endpoint(e)

    def delete_endpoint(self, name):
        with self._lock, self._db:
            self._db.execute("DELETE FROM plan_endpoints WHERE endpoint=?", (name,))
            return self._db.execute("DELETE FROM endpoints WHERE name=?", (name,)).rowcount > 0

    # ---- plans -------------------------------------------------------------
    def plans(self):
        access = {}
        for plan, endpoint in self._db.execute("SELECT plan, endpoint FROM plan_endpoints ORDER BY endpoint"):
            access.setdefault(plan, []).append(endpoint)
        rows = self._db.execute(f"SELECT {','.join(PLAN_COLS)} FROM plans ORDER BY monthly_price_cents, name")
        return {r[0]: Plan(*r, endpoints=tuple(access.get(r[0], ()))) for r in rows}

    def _write_plan(self, plan):
        self._db.execute(
            f"INSERT INTO plans ({','.join(PLAN_COLS)}) VALUES ({','.join('?' * len(PLAN_COLS))}) "
            "ON CONFLICT(name) DO UPDATE SET "
            + ",".join(f"{c}=excluded.{c}" for c in PLAN_COLS[1:]),
            [getattr(plan, c) for c in PLAN_COLS],
        )
        self._db.execute("DELETE FROM plan_endpoints WHERE plan=?", (plan.name,))
        for ep in plan.endpoints:
            if not self._db.execute("SELECT 1 FROM endpoints WHERE name=?", (ep,)).fetchone():
                raise UnknownEndpoint(ep)
            self._db.execute("INSERT INTO plan_endpoints VALUES (?,?)", (plan.name, ep))

    def upsert_plan(self, plan):
        with self._lock, self._db:
            self._write_plan(plan)

    def delete_plan(self, name):
        with self._lock, self._db:
            if self._db.execute("SELECT 1 FROM consumers WHERE plan=?", (name,)).fetchone():
                raise PlanInUse(name)
            self._db.execute("DELETE FROM plan_endpoints WHERE plan=?", (name,))
            return self._db.execute("DELETE FROM plans WHERE name=?", (name,)).rowcount > 0

    # ---- consumers ---------------------------------------------------------
    def _keys(self, name):
        rows = self._db.execute(
            "SELECT id, label, api_key, created_at FROM keys WHERE consumer=? AND revoked=0 ORDER BY id", (name,)
        )
        return [dict(zip(("id", "label", "api_key", "created_at"), r)) for r in rows]

    def _consumer(self, row):
        return {"name": row[0], "plan": row[1], "created_at": row[2], "keys": self._keys(row[0])}

    def create(self, name, plan):
        """Raises sqlite3.IntegrityError if the name exists or the plan is unknown."""
        with self._lock, self._db:
            self._db.execute("INSERT INTO consumers VALUES (?,?,?)", (name, plan, _now()))
            self._add_key(name, "default")
        return self.get(name)

    def list(self):
        rows = self._db.execute("SELECT name, plan, created_at FROM consumers ORDER BY name").fetchall()
        return [self._consumer(r) for r in rows]

    def get(self, name):
        row = self._db.execute("SELECT name, plan, created_at FROM consumers WHERE name=?", (name,)).fetchone()
        return self._consumer(row) if row else None

    def set_plan(self, name, plan):
        with self._lock, self._db:
            return self._db.execute("UPDATE consumers SET plan=? WHERE name=?", (plan, name)).rowcount > 0

    def delete(self, name):
        with self._lock, self._db:
            self._db.execute("DELETE FROM keys WHERE consumer=?", (name,))
            return self._db.execute("DELETE FROM consumers WHERE name=?", (name,)).rowcount > 0

    # ---- keys --------------------------------------------------------------
    def _add_key(self, name, label):
        key = secrets.token_urlsafe(24)
        cur = self._db.execute(
            "INSERT INTO keys (consumer, api_key, label, created_at) VALUES (?,?,?,?)", (name, key, label, _now())
        )
        return {"id": cur.lastrowid, "label": label, "api_key": key}

    def add_key(self, name, label="generated"):
        with self._lock, self._db:
            if not self._db.execute("SELECT 1 FROM consumers WHERE name=?", (name,)).fetchone():
                return None
            return self._add_key(name, label)

    def revoke_key(self, name, key_id):
        with self._lock, self._db:
            return (
                self._db.execute(
                    "UPDATE keys SET revoked=1 WHERE id=? AND consumer=? AND revoked=0", (key_id, name)
                ).rowcount
                > 0
            )
