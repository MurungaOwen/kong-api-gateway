from app import invoice
from app.plans import DEFAULT_PLANS

PLANS = {p.name: p for p in DEFAULT_PLANS}


def test_free_plan_within_allowance_costs_nothing():
    inv = invoice.compute("a", PLANS["free"], "2026-09", 900, 900, {})
    assert inv["total_cents"] == 0 and inv["usage"]["overage_units"] == 0


def test_pro_overage_is_prorated_and_rounded():
    # 100_000 included; 2_500 over at 50c/1k = 125c
    inv = invoice.compute("a", PLANS["pro"], "2026-09", 102_500, 1, {})
    assert inv["usage"]["overage_units"] == 2_500
    assert inv["total_cents"] == 4_900 + 125
    # 1 unit over at 50c/1k = 0.05c -> rounds to 0
    assert invoice.compute("a", PLANS["pro"], "2026-09", 100_001, 1, {})["total_cents"] == 4_900


def test_free_plan_overage_is_free():
    # free has no overage price (rate limited/blocked by policy elsewhere)
    assert invoice.compute("a", PLANS["free"], "2026-09", 5_000, 1, {})["total_cents"] == 0
