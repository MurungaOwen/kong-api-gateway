from dataclasses import dataclass


@dataclass(frozen=True)
class Plan:
    name: str
    per_minute: int          # enforced at Kong via rate-limiting
    monthly_included: int    # free calls before overage billing
    overage_per_1k_cents: int


PLANS = {
    p.name: p
    for p in (
        Plan("free", per_minute=10, monthly_included=1_000, overage_per_1k_cents=0),
        Plan("pro", per_minute=100, monthly_included=100_000, overage_per_1k_cents=50),
        Plan("enterprise", per_minute=1000, monthly_included=1_000_000, overage_per_1k_cents=20),
    )
}
