from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Upstream:
    """A backend service Kong load-balances across (a Kong `upstream` with targets)."""
    name: str
    targets: tuple                    # ("host:port", ...): one per replica, or a DNS name with many A records
    algorithm: str = "round-robin"    # round-robin | least-connections
    health_path: str = "/health"      # actively probed by Kong
    health_interval: int = 5          # seconds between probes

    def dict(self):
        d = asdict(self)
        d["targets"] = list(self.targets)
        return d


@dataclass(frozen=True)
class Endpoint:
    """A billable API endpoint exposed through Kong as its own route."""
    name: str
    path: str            # public path on the gateway, e.g. /api/report
    units: int           # billing weight of one successful call
    description: str = ""
    upstream: str = "product-api"   # which backend serves it
    upstream_path: str = ""         # path on the backend; empty = public path minus the /api prefix

    def dict(self):
        return asdict(self)

    def backend_path(self):
        return self.upstream_path or self.path[len("/api"):]

    def dict(self):
        return asdict(self)


@dataclass(frozen=True)
class Plan:
    name: str
    monthly_price_cents: int    # flat subscription fee
    monthly_included: int       # units included in the fee
    overage_per_1k_cents: int   # price per 1000 units beyond the included amount
    # Rate limits enforced by Kong per subscriber. None = no limit for that window.
    per_second: Optional[int] = None
    per_minute: Optional[int] = None
    per_hour: Optional[int] = None
    per_day: Optional[int] = None
    endpoints: tuple = field(default_factory=tuple)  # names of endpoints this plan may call

    def dict(self):
        d = asdict(self)
        d["endpoints"] = list(self.endpoints)
        return d

    def limits(self):
        """Kong rate-limiting plugin config fragment for the windows that are set."""
        pairs = (("second", self.per_second), ("minute", self.per_minute), ("hour", self.per_hour), ("day", self.per_day))
        return {k: v for k, v in pairs if v}


DEFAULT_UPSTREAMS = (Upstream("product-api", ("product-api:8080",)),)

# Seeded on first start; afterwards everything lives in the DB and is edited via the API/dashboard.
DEFAULT_ENDPOINTS = (
    Endpoint("quote", "/api/quote", 1, "A quote of the day"),
    Endpoint("whoami", "/api/whoami", 1, "Which replica answered (load balancing demo)"),
    Endpoint("echo", "/api/echo", 1, "Echoes the headers Kong forwarded"),
    Endpoint("report", "/api/report", 5, "Expensive report, billed at 5 units"),
)

DEFAULT_PLANS = (
    Plan("free", 0, 1_000, 0, per_minute=10, per_day=500, endpoints=("quote", "whoami")),
    Plan("pro", 4_900, 100_000, 50, per_second=20, per_minute=100, endpoints=("quote", "whoami", "echo", "report")),
    Plan("enterprise", 49_900, 1_000_000, 20, per_minute=1000, endpoints=("quote", "whoami", "echo", "report")),
)
