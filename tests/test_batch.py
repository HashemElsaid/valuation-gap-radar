"""Tests for batch mode: reading the CSV, matching names, and one report row per deal."""

import io

import pandas as pd
import pytest

from radar.batch import assess_deals, match_area, match_building, read_deals

JVC = "Jumeirah Village Circle"


def make_sales(n, project="Tower A"):
    """n identical recent sales: 70 sqm (753 sqft) 1-bed apartments in JVC at AED 10,000/sqm."""
    return pd.DataFrame({
        "date": pd.to_datetime(["2026-09-01"] * n),
        "area": JVC, "project": project, "property_type": "Apartment", "bedrooms": 1,
        "size_sqm": 70.0, "price_aed": 700_000.0, "price_per_sqm": 10_000.0,
    })


def deals_csv(text):
    return read_deals(io.StringIO(text))


HEADER = "deal_id,area,building,property_type,bedrooms,size_sqft,price,cash_available\n"


# --- Reading the CSV -------------------------------------------------------

def test_headers_are_matched_ignoring_case_and_spaces():
    deals = deals_csv(" Deal_ID ,AREA,Property_Type,Bedrooms,Size_SQFT,Price,Cash_Available\nP-1,JVC,apartment,1,753,700000,200000\n")

    assert "deal_id" in deals.columns and "size_sqft" in deals.columns


def test_missing_columns_are_named_in_the_error():
    with pytest.raises(ValueError, match="price, cash_available"):
        deals_csv("deal_id,area,property_type,bedrooms,size_sqft\nP-1,JVC,apartment,1,753\n")


# --- Matching names --------------------------------------------------------

def test_area_names_match_shorthand_and_any_case():
    areas = {JVC, "Dubai Marina"}

    assert match_area("JVC", areas) == JVC
    assert match_area("jumeirah village circle", areas) == JVC
    assert match_area("Marina", areas) == "Dubai Marina"
    assert match_area("Al Reem Island", areas) is None
    assert match_area(float("nan"), areas) is None  # blank cell


def test_building_matches_ignoring_case_and_spaces():
    sales = make_sales(1, project="Binghatti Amber")

    assert match_building("binghatti  AMBER", sales, JVC) == "Binghatti Amber"
    assert match_building("Unknown Tower", sales, JVC) is None


# --- The report ------------------------------------------------------------

def test_every_deal_gets_a_row_and_the_riskiest_come_first():
    deals = deals_csv(HEADER + "\n".join([
        "P-low,JVC,,apartment,1,753,700000,200000",     # at the estimate
        "P-high,JVC,,apartment,1,753,800000,200000",    # 14% above
        "P-bad,Al Reem Island,,apartment,1,753,700000,200000",
        "P-few,JVC,,apartment,3,753,700000,200000",     # no 3-bed sales
    ]))
    report = assess_deals(make_sales(12), deals)

    assert report["deal_id"].tolist() == ["P-high", "P-low", "P-bad", "P-few"]  # unknowns keep CSV order
    assert report.set_index("deal_id")["risk"].to_dict() == {
        "P-high": "High", "P-low": "Low", "P-bad": "Unknown", "P-few": "Unknown",
    }


def test_cash_columns_for_an_assessed_deal():
    # Price 800k vs estimate 700k: the loan drops from 640k to 560k, so 80k more cash.
    deals = deals_csv(HEADER + "P-1,JVC,,apartment,1,753,800000,200000\n")
    row = assess_deals(make_sales(12), deals).iloc[0]

    assert row["estimate"] == pytest.approx(700_000, rel=0.001)
    assert row["extra_cash_median"] == pytest.approx(80_000, rel=0.01)
    assert row["short_median"] == pytest.approx(40_000, rel=0.01)  # needs 240k, has 200k
    assert "Form F" in row["advisor_note"]


def test_problems_are_explained_in_notes():
    deals = deals_csv(HEADER + "\n".join([
        "P-area,Al Reem Island,,apartment,1,753,700000,200000",
        "P-type,JVC,,office,1,753,700000,200000",
        "P-beds,JVC,,apartment,two,753,700000,200000",
        "P-price,JVC,,apartment,1,753,,200000",
        "P-few,JVC,,apartment,3,753,700000,200000",
        "P-big,JVC,,apartment,1,753,5000000,1200000",
        "P-bldg,JVC,Unknown Tower,apartment,1,753,700000,200000",
    ]))
    notes = assess_deals(make_sales(12), deals).set_index("deal_id")["notes"]

    assert "unknown area 'Al Reem Island'" in notes["P-area"]
    assert "apartment or villa" in notes["P-type"]
    assert "bedrooms" in notes["P-beds"]
    assert "price must be" in notes["P-price"]
    assert "too few comparable sales" in notes["P-few"]
    assert "maximum price" in notes["P-big"]
    assert "building not found" in notes["P-bldg"]


def test_studio_and_numbers_with_commas_are_understood():
    sales = make_sales(12).assign(bedrooms=0)
    deals = deals_csv(HEADER + 'P-1,JVC,,Apartment,Studio,753,"700,000","200,000"\n')
    row = assess_deals(sales, deals).iloc[0]

    assert row["bedrooms"] == 0
    assert row["price"] == 700_000
    assert row["risk"] == "Low"
