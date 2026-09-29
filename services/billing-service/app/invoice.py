"""Pure invoice maths: usage in, invoice out (no I/O, easy to test)."""
from .plans import Plan


def compute(consumer: str, plan: Plan, month: str, units: int, calls: int, by_route: dict) -> dict:
    included_used = min(units, plan.monthly_included)
    overage_units = max(0, units - plan.monthly_included)
    # Overage is billed pro rata per 1000 units, rounded half up to whole cents.
    overage_cents = (overage_units * plan.overage_per_1k_cents + 500) // 1000
    lines = [
        {"description": f"{plan.name} plan ({month})", "cents": plan.monthly_price_cents},
        {
            "description": f"Overage: {overage_units} units x ${plan.overage_per_1k_cents / 100:.2f}/1k",
            "cents": overage_cents,
        },
    ]
    return {
        "consumer": consumer,
        "plan": plan.name,
        "month": month,
        "usage": {
            "units": units,
            "calls": calls,
            "included": plan.monthly_included,
            "included_used": included_used,
            "overage_units": overage_units,
            "by_route": by_route,
        },
        "lines": lines,
        "total_cents": sum(line["cents"] for line in lines),
    }
