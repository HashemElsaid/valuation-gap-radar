"""Tests for the comps engine: comp selection, weighting, the estimate and the risk score."""

import pandas as pd
import pytest

from radar import config
from radar.comps import (
    confidence_level,
    estimate_value,
    find_comps,
    gap_risk,
    recency_weights,
    weighted_percentiles,
)


def make_sales(n, ppsqm=10_000, size=70.0, date="2026-06-01", **fields):
    """n identical sales: a 70 sqm 1-bed apartment in Tower A, JVC, at AED 10,000/sqm."""
    row = {"area": "JVC", "project": "Tower A", "property_type": "Apartment", "bedrooms": 1}
    row.update(fields)
    return pd.DataFrame({
        "date": pd.to_datetime([date] * n),
        **row,
        "size_sqm": size,
        "price_aed": ppsqm * size,
        "price_per_sqm": float(ppsqm),
    })


# --- Choosing comps --------------------------------------------------------

def test_comps_must_match_area_type_bedrooms_and_size():
    sales = pd.concat([
        make_sales(1),                          # match
        make_sales(1, size=83.0),               # +19%: match
        make_sales(1, size=85.0),               # +21%: too big
        make_sales(1, area="Arjan"),            # wrong area
        make_sales(1, bedrooms=2),              # wrong bedrooms
        make_sales(1, property_type="Villa"),   # wrong type
    ])
    comps, _ = find_comps(sales, "JVC", "Apartment", 1, 70)

    assert comps["size_sqm"].tolist() == [70.0, 83.0]


def test_same_project_is_used_when_it_has_enough_sales():
    sales = pd.concat([make_sales(config.MIN_PROJECT_COMPS), make_sales(10, project="Tower B")])
    comps, basis = find_comps(sales, "JVC", "Apartment", 1, 70, project="Tower A")

    assert basis == "project"
    assert set(comps["project"]) == {"Tower A"}


def test_falls_back_to_the_area_when_the_project_has_too_few_sales():
    sales = pd.concat([make_sales(config.MIN_PROJECT_COMPS - 1), make_sales(10, project="Tower B")])
    comps, basis = find_comps(sales, "JVC", "Apartment", 1, 70, project="Tower A")

    assert basis == "area"
    assert len(comps) == config.MIN_PROJECT_COMPS - 1 + 10


# --- Weighting -------------------------------------------------------------

def test_recency_weight_halves_every_half_life():
    as_of = pd.Timestamp("2026-10-01")
    dates = pd.Series([as_of, as_of - pd.Timedelta(days=config.RECENCY_HALF_LIFE_DAYS)])

    assert recency_weights(dates, as_of).tolist() == pytest.approx([1.0, 0.5])


def test_weighted_percentiles():
    # Equal weights: the plain median.
    assert weighted_percentiles([10, 30, 20], [1, 1, 1], 0.5) == pytest.approx(20)
    # More weight on the low value pulls the median down.
    assert weighted_percentiles([10, 20, 30], [5, 1, 1], 0.5) < 20


# --- The estimate ----------------------------------------------------------

def test_no_estimate_with_too_few_comps():
    assert estimate_value(make_sales(config.MIN_COMPS - 1), "JVC", "Apartment", 1, 70) is None


def test_estimate_is_comp_price_per_sqm_times_size():
    est = estimate_value(make_sales(12), "JVC", "Apartment", 1, 75)

    assert est.value_median == pytest.approx(10_000 * 75)
    assert est.value_p25 == est.value_p75 == pytest.approx(10_000 * 75)  # identical comps
    assert est.n_comps == 12
    assert est.confidence == "High"


def test_estimate_ignores_sales_after_the_as_of_date():
    sales = pd.concat([make_sales(5, date="2026-01-01"), make_sales(5, ppsqm=20_000, date="2026-09-01")])
    est = estimate_value(sales, "JVC", "Apartment", 1, 70, as_of="2026-06-01")

    assert est.n_comps == 5
    assert est.ppsqm_median == pytest.approx(10_000)


def test_confidence_levels():
    assert confidence_level(10, 0.10) == "High"
    assert confidence_level(50, 0.20) == "Medium"  # many comps, but they disagree
    assert confidence_level(5, 0.10) == "Medium"  # agree, but too few for High
    assert confidence_level(4, 0.05) == "Low"
    assert confidence_level(100, 0.40) == "Low"


# --- Gap risk --------------------------------------------------------------

@pytest.mark.parametrize("price, level", [
    (700_000, "Low"),     # at the estimate
    (735_000, "Medium"),  # 5% above
    (777_000, "High"),    # 11% above
])
def test_gap_risk_levels_with_a_confident_estimate(price, level):
    est = estimate_value(make_sales(12), "JVC", "Apartment", 1, 70)  # AED 700,000, High confidence

    assert gap_risk(price, est).level == level


def test_low_confidence_adds_a_buffer():
    est = estimate_value(make_sales(config.MIN_COMPS), "JVC", "Apartment", 1, 70)  # Low confidence
    risk = gap_risk(735_000, est)  # 5% above, plus the Low-confidence buffer

    assert risk.premium == pytest.approx(0.05)
    assert risk.buffer == config.CONFIDENCE_BUFFER["Low"]
    assert risk.level == "High"
