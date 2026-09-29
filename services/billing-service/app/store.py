import secrets
import sqlite3
import threading


class Store:
    """Tiny SQLite store: consumers with a plan and an API key."""

    def __init__(self, path=":memory:"):
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS consumers ("
            "name TEXT PRIMARY KEY, plan TEXT NOT NULL, api_key TEXT NOT NULL UNIQUE)"
        )

    def create(self, name, plan):
        key = secrets.token_urlsafe(24)
        with self._lock, self._db:
            self._db.execute("INSERT INTO consumers VALUES (?,?,?)", (name, plan, key))
        return {"name": name, "plan": plan, "api_key": key}

    def list(self):
        rows = self._db.execute("SELECT name, plan, api_key FROM consumers ORDER BY name")
        return [dict(zip(("name", "plan", "api_key"), r)) for r in rows]

    def set_plan(self, name, plan):
        with self._lock, self._db:
            cur = self._db.execute("UPDATE consumers SET plan=? WHERE name=?", (plan, name))
        return cur.rowcount > 0
