"""Regenerate illustrative pricing scenarios; no costs here are measurements."""
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path

D = Decimal


def money(value):
    return float(value.quantize(D(".01"), rounding=ROUND_HALF_UP))


SCENARIOS = {
    "low_touch": (D(".25"), D("1")),
    "working_case": (D(".65"), D("3")),
    "stress": (D("1.50"), D("8")),
}
PLANS = [
    ("single", D("12"), 1, D(".065")),
    ("three_pack", D("29"), 3, D(".065")),
    ("creator_deferred", D("24"), 3, D(".07")),
    ("old_launch_test_not_recommended", D("4.99"), 1, D(".065")),
]


def calculate():
    rows = []
    for name, price, projects, rate in PLANS:
        for scenario, (infra, minutes) in SCENARIOS.items():
            service = infra + minutes * D(".5")
            fee = price * rate + D(".50")
            refunds = price * D(".03")
            contribution = price - fee - refunds - projects * service
            rows.append(dict(
                plan=name, price=float(price), projects=projects, scenario=scenario,
                fee=money(fee), refund_reserve=money(refunds),
                service_cost_per_project=money(service),
                contribution_before_CAC_and_fixed=money(contribution),
                contribution_pct=money(contribution / price * 100),
            ))
    fixed = []
    variable = D("12") * D(".065") + D(".5") + D("12") * D(".03") + D("2.15")
    for quantity in (25, 100, 250, 1000):
        allocation = D("150") / quantity
        fixed.append(dict(
            paid_projects=quantity, fixed_cost_per_project=money(allocation),
            modeled_cost_single_including_fixed=money(variable + allocation),
            remaining_single_before_CAC=money(D("12") - variable - allocation),
        ))
    # An explicitly hypothetical quota-exhaustion session, not cloud unit prices.
    maximum_infra = 200 * D(".02") + 11 * D(".10") + D(".20")
    maximum_service = maximum_infra + 8 * D(".50")
    maximum_rows = [dict(
        plan=name,
        contribution_before_CAC_and_fixed=money(
            price - (price * rate + D(".50")) - price * D(".03")
            - projects * maximum_service
        ),
    ) for name, price, projects, rate in PLANS[:3]]
    report = {
        "kind": "illustrative-pricing-scenarios-not-observed-costs",
        "currency": "USD",
        "basis": "Tax-exclusive prices; all included project credits redeemed. Main scenarios do NOT establish cost at maximum preview/rebuild use. Round only after calculation. Fixed and incremental infrastructure must not double-count worker capacity.",
        "assumptions": {
            "fixed_monthly_infrastructure_budget_not_quote": 150,
            "support_hourly_opportunity_cost": 30,
            "base_MoR_percent": 5,
            "modeled_crossborder_uplift_percent": 1.5,
            "subscription_uplift_percent": .5,
            "fixed_payment_fee": .5,
            "refund_reserve_percent": 3,
            "scenario_inputs": {name: {
                "incremental_infra_and_free_funnel_reserve_per_project": float(infra),
                "support_minutes_per_project": float(minutes),
            } for name, (infra, minutes) in SCENARIOS.items()},
            "excludes": ["sales-tax effects on processing fee", "FX/PayPal/payout/dispute fees", "income tax", "CAC", "development compensation", "unmeasured provider-specific costs"],
        },
        "rows": rows,
        "fixed_allocation_single_project": fixed,
        "payment_sensitivity_single_working_case": {
            "hypothetical_sales_tax_percent": 20,
            "extra_processing_fee_on_tax": money(D("12") * D(".20") * D(".065")),
            "hypothetical_non_US_bank_payout_percent": 1,
            "approximate_payout_charge_on_price_less_processing": money((D("12") - D("1.28") - D(".156")) * D(".01")),
            "contribution_after_these_two_extras": money(D("8.21") - D(".156") - D(".10564")),
            "note": "Sensitivity only: payout base and refund timing depend on settlement. Taxes collected are not product revenue. PayPal and FX remain excluded.",
        },
        "quota_exhaustion_sensitivity": {
            "hypothetical_cost_per_preview": .02,
            "previews_per_project": 200,
            "hypothetical_cost_per_build": .10,
            "builds_per_project": 11,
            "other_incremental_infra_per_project": .20,
            "support_minutes_per_project": 8,
            "incremental_infra_per_project": money(maximum_infra),
            "service_cost_per_project": money(maximum_service),
            "rows": maximum_rows,
            "note": "Separate stress scenario: demonstrates why actual deployment measurements at quota exhaustion are a launch gate, not a claim that these are actual unit costs.",
        },
    }
    assert rows[1]["contribution_before_CAC_and_fixed"] == 8.21
    assert rows[4]["contribution_before_CAC_and_fixed"] == 19.30
    assert rows[7]["contribution_before_CAC_and_fixed"] == 14.65
    assert maximum_rows[0]["contribution_before_CAC_and_fixed"] == 1.06
    return report


if __name__ == "__main__":
    destination = Path(__file__).with_name("pricing-economics.json")
    destination.write_text(json.dumps(calculate(), indent=2) + "\n")
    print(f"Wrote {destination}")
