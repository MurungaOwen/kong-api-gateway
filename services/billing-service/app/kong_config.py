"""Render Kong declarative config from billing data (billing = source of truth).

Everything Kong needs is generated here: routes, plugins, upstream, consumers.
"""
import yaml

JWT_ISSUER = "dashboard"  # the `iss` claim Kong maps to the dashboard-admin consumer


NO_PLAN = "__no_plan__"  # ACL needs a non-empty allow list; an endpoint no plan includes is locked


def _metered_plugins(units, allowed_plans):
    """Plugins shared by every billable route, in the order they read best."""
    return [
        # hide_credentials: the upstream never sees the customer's API key.
        {"name": "key-auth", "config": {"key_names": ["apikey"], "hide_credentials": True}},
        # Entitlements: a consumer's ACL group is their plan; only plans that include this
        # endpoint are allowed, everyone else gets 403.
        {"name": "acl", "config": {"allow": sorted(allowed_plans) or [NO_PLAN], "hide_groups_header": True}},
        {"name": "request-transformer", "config": {"add": {"headers": ["X-Gateway:kong-billing-demo"]}}},
        # Metering path A: stock http-log, batched.
        {
            "name": "http-log",
            "config": {
                "http_endpoint": "http://usage-ingest:8100/ingest",
                "queue": {"max_batch_size": 20, "max_coalescing_delay": 2},
            },
        },
        # Metering path B: custom plugin with billing semantics (plan, weighted units).
        {
            "name": "billing-meter",  # our custom Lua plugin
            "config": {"ingest_url": "http://usage-ingest:8100/events", "units": units},
        },
    ]


def _endpoint_service(ep, plans):
    """One Kong service+route per catalog endpoint: /api/report -> upstream /report."""
    allowed = [p.name for p in plans.values() if ep.name in p.endpoints]
    return {
        "name": f"endpoint-{ep.name}",
        # Host = the Kong upstream's name, so Kong load-balances across its targets.
        "protocol": "http",
        "host": ep.upstream,
        "port": 80,  # ignored when host is an upstream: the targets carry their own ports
        "path": ep.backend_path(),
        "tags": ["endpoint"],
        "routes": [
            {
                "name": f"route-{ep.name}",
                "paths": [ep.path],
                "strip_path": True,
                "plugins": _metered_plugins(ep.units, allowed),
            }
        ],
    }


def render(consumers, plans, endpoints, upstreams, jwt_secret):
    """OSS Kong has no consumer-group rate limiting (that is Enterprise's
    rate-limiting-advanced), so the plan's limits are attached per consumer."""
    return {
        "_format_version": "3.0",
        # Global: /metrics on the status listener. In 3.x the per-request series are opt-in.
        "plugins": [
            {
                "name": "prometheus",
                "config": {
                    "per_consumer": True,
                    "status_code_metrics": True,
                    "latency_metrics": True,
                    "bandwidth_metrics": True,
                    "upstream_health_metrics": True,
                },
            }
        ],
        "upstreams": [_upstream(u) for u in upstreams.values()],
        "services": [_endpoint_service(ep, plans) for ep in endpoints.values()]
        + [
            {
                "name": "billing-service",
                "url": "http://billing-service:8090",
                "routes": [
                    {
                        "name": "billing-route",
                        "paths": ["/billing"],
                        "strip_path": True,
                        # The admin/dashboard path: JWT (HS256) instead of API keys.
                        "plugins": [{"name": "jwt", "config": {"key_claim_name": "iss", "claims_to_verify": ["exp"]}}],
                    }
                ],
            }
        ],
        "consumers": [
            {
                "username": "dashboard-admin",
                "jwt_secrets": [{"key": JWT_ISSUER, "secret": jwt_secret, "algorithm": "HS256"}],
            }
        ]
        + [_consumer(c, plans[c["plan"]]) for c in consumers],
    }


def _upstream(u):
    return {
        "name": u.name,
        "algorithm": u.algorithm,
        "healthchecks": {
            "active": {
                "http_path": u.health_path,
                "healthy": {"interval": u.health_interval, "successes": 2},
                "unhealthy": {"interval": u.health_interval, "http_failures": 2, "timeouts": 2},
            },
            "passive": {"unhealthy": {"http_failures": 3, "http_statuses": [500, 502, 503]}},
        },
        # A target can be a DNS name with many A records (Docker: `--scale service=N`),
        # so replicas need no config change.
        "targets": [{"target": t} for t in u.targets],
    }


def _consumer(c, plan):
    out = {
        "username": c["name"],
        "custom_id": c["name"],
        "tags": [f"plan:{c['plan']}"],
        "keyauth_credentials": [{"key": k["api_key"]} for k in c["keys"]],
        "acls": [{"group": c["plan"]}],
    }
    limits = plan.limits()
    if limits:
        out["plugins"] = [
            {"name": "rate-limiting", "config": {**limits, "policy": "local", "limit_by": "consumer"}}
        ]
    return out


def dump(consumers, plans, endpoints, upstreams, jwt_secret):
    return yaml.safe_dump(render(consumers, plans, endpoints, upstreams, jwt_secret), sort_keys=False)
