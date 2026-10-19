"""Tests for the advisor note: the right message for each risk and confidence level."""

import pandas as pd

from radar.advisor import advisor_note, describe_home
from radar.cash import scenario_table
from radar.comps import estimate_value, gap_risk


def make_sales(n):
    """n identical recent sales: 70 sqm 1-bed apartments in JVC at AED 10,000/sqm (AED 929/sqft)."""
    return pd.DataFrame({
        "date": pd.to_datetime(["2026-09-01"] * n),
        "area": "JVC", "project": "Tower A", "property_type": "Apartment", "bedrooms": 1,
        "size_sqm": 70.0, "price_aed": 700_000.0, "price_per_sqm": 10_000.0,
    })


def note_for(price, cash_available, n_comps=12):
    """The note for a 70 sqm 1-bed in JVC, estimated at AED 700,000."""
    est = estimate_value(make_sales(n_comps), "JVC", "Apartment", 1, 70)
    risk = gap_risk(price, est)
    scenarios = scenario_table(price, est.valuations, cash_available)
    return advisor_note(area="JVC", property_type="Apartment", bedrooms=1, size_sqm=70, price=price,
                        cash_available=cash_available, estimate=est, risk=risk, scenarios=scenarios)


def test_describe_home():
    assert describe_home("Apartment", 0) == "studio apartments"
    assert describe_home("Apartment", 2) == "2-bed apartments"
    assert describe_home("Villa", 4) == "4-bed villas"


def test_high_risk_note_gives_the_cash_at_stake_and_what_to_do():
    # AED 800,000 is 14% above AED 700,000. A valuation at 700k means a loan of
    # 560k, so the buyer needs 240k instead of 160k: 80k more, and 90k more than the 150k they have.
    note = note_for(price=800_000, cash_available=150_000)

    assert "AED 929 per sqft" in note
    assert "14% above" in note
    assert "AED 80,000 more cash" in note
    assert "AED 90,000 short" in note
    assert "Form F" in note


def test_low_risk_note_is_reassuring():
    note = note_for(price=700_000, cash_available=150_000)

    assert "0% above" in note
    assert "unlikely" in note
    assert "Form F" not in note


def test_a_price_far_below_the_estimate_asks_to_check_the_inputs():
    note = note_for(price=350_000, cash_available=150_000)  # half the estimate

    assert "unlikely" in note
    assert "double-check" in note


def test_low_confidence_note_suggests_choosing_the_building():
    note = note_for(price=700_000, cash_available=150_000, n_comps=3)

    assert "rough guide" in note
    assert "Choosing the building" in note
