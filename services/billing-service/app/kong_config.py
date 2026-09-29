"""Render Kong declarative config from billing data (billing = source of truth)."""
import yaml

from .plans import PLANS


def render(consumers):
    """OSS Kong has no consumer-group rate limiting (that is Enterprise's
    rate-limiting-advanced), so the plan limit is attached per consumer."""
    return {
        "_format_version": "3.0",
        "plugins": [
            {
                "name": "http-log",
                "config": {
                    "http_endpoint": "http://usage-ingest:8100/ingest",
                    "queue": {"max_batch_size": 20, "max_coalescing_delay": 2},
                },
            }
        ],
        "services": [
            {
                "name": "product-api",
                "url": "http://product-api:8080",
                "routes": [
                    {
                        "name": "product-api-route",
                        "paths": ["/api"],
                        "strip_path": True,
                        "plugins": [
                            {"name": "key-auth", "config": {"key_names": ["apikey"]}},
                            {
                                "name": "billing-meter",
                                "config": {"ingest_url": "http://usage-ingest:8100/events", "units": 1},
                            },
                        ],
                    }
                ],
            }
        ],
        "consumers": [
            {
                "username": c["name"],
                "custom_id": c["name"],
                "tags": [f"plan:{c['plan']}"],
                "keyauth_credentials": [{"key": c["api_key"]}],
                "plugins": [
                    {
                        "name": "rate-limiting",
                        "config": {
                            "minute": PLANS[c["plan"]].per_minute,
                            "policy": "local",
                            "limit_by": "consumer",
                        },
                    }
                ],
            }
            for c in consumers
        ],
    }


def dump(consumers):
    return yaml.safe_dump(render(consumers), sort_keys=False)
