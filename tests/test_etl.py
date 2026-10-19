"""Tests for the ETL: each cleaning rule, and the tidy-up of names and numbers."""

import pandas as pd

from radar.etl import build_sample, clean, clean_area_name, parse_bedrooms


def raw_row(**overrides):
    """One raw DLD row for a valid apartment sale. Override fields to break it."""
    row = {
        "TRANSACTION_NUMBER": "good-flat",
        "INSTANCE_DATE": "2026-06-01 10:00:00",
        "PROCEDURE_EN": "Sale",
        "IS_OFFPLAN_EN": "Ready",
        "IS_FREE_HOLD_EN": "Free Hold",
        "USAGE_EN": "Residential",
        "AREA_EN": "JUMEIRAH VILLAGE CIRCLE",
        "PROJECT_EN": "Binghatti  Amber",
        "PROP_TYPE_EN": "Unit",
        "PROP_SB_TYPE_EN": "Flat",
        "ROOMS_EN": "1 B/R",
        "PROCEDURE_AREA": "70",
        "ACTUAL_AREA": "70",
        "TRANS_VALUE": "910000",
    }
    row.update(overrides)
    return row


def test_clean_keeps_only_valid_resales():
    raw = pd.DataFrame([
        raw_row(),
        raw_row(TRANSACTION_NUMBER="good-villa", PROP_TYPE_EN="Building", PROP_SB_TYPE_EN="Villa",
                ROOMS_EN="3 B/R", PROCEDURE_AREA="250", ACTUAL_AREA="250", TRANS_VALUE="4000000"),
        raw_row(),  # same transaction number again
        raw_row(TRANSACTION_NUMBER="delayed-sell", PROCEDURE_EN="Delayed Sell"),
        raw_row(TRANSACTION_NUMBER="off-plan", IS_OFFPLAN_EN="Off-Plan"),
        raw_row(TRANSACTION_NUMBER="office", PROP_SB_TYPE_EN="Office", ROOMS_EN="Office"),
        raw_row(TRANSACTION_NUMBER="villa-plot", PROP_TYPE_EN="Land", PROP_SB_TYPE_EN="Villa", ROOMS_EN=None),
        raw_row(TRANSACTION_NUMBER="half-share", PROCEDURE_AREA="35"),
        raw_row(TRANSACTION_NUMBER="penthouse", ROOMS_EN="PENTHOUSE"),
        raw_row(TRANSACTION_NUMBER="too-old", INSTANCE_DATE="2024-01-01 10:00:00"),
        raw_row(TRANSACTION_NUMBER="nominal-price", TRANS_VALUE="70000"),  # AED 1,000 per sqm
        raw_row(TRANSACTION_NUMBER="bad-price", TRANS_VALUE="not a number"),
    ])

    sales = clean(raw, verbose=False)

    assert sorted(sales["transaction_id"]) == ["good-flat", "good-villa"]


def test_clean_tidies_names_and_computes_price_per_sqm():
    sale = clean(pd.DataFrame([raw_row()]), verbose=False).iloc[0]

    assert sale["area"] == "Jumeirah Village Circle"
    assert sale["project"] == "Binghatti Amber"  # double space collapsed
    assert sale["property_type"] == "Apartment"
    assert sale["bedrooms"] == 1
    assert sale["price_per_sqm"] == 13_000  # 910,000 / 70


def test_parse_bedrooms():
    rooms = pd.Series(["Studio", "2 B/R", " 3 B/R ", "PENTHOUSE", None])
    beds = parse_bedrooms(rooms)

    assert beds.iloc[:3].tolist() == [0, 2, 3]
    assert beds.iloc[3:].isna().all()


def test_clean_area_name():
    assert clean_area_name("JUMEIRAH VILLAGE CIRCLE") == "Jumeirah Village Circle"
    assert clean_area_name("Business Bay") == clean_area_name("BUSINESS BAY")
    assert clean_area_name("MBR DISTRICT 1") == "MBR District 1"  # acronym kept
    assert clean_area_name("BURJ KHALIFA") == "Downtown Dubai"  # alias applied


def test_sample_picks_busiest_areas_for_each_property_type():
    sales = pd.DataFrame({
        "date": pd.to_datetime(["2026-01-01"] * 4),
        "area": ["A", "A", "B", "C"],
        "property_type": ["Apartment", "Apartment", "Apartment", "Villa"],
    })
    # Area C has fewer sales than A or B overall, but it is the busiest villa area.
    sample = build_sample(sales, n_areas=1)

    assert set(zip(sample["area"], sample["property_type"])) == {("A", "Apartment"), ("C", "Villa")}
