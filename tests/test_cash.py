"""Tests for the fee and cash math. Expected numbers are worked out by hand in the comments.

The fee tests use Sooner's own published examples, so if they pass, our fee
lines match joinsooner.com. The running example elsewhere is a AED 2,000,000
home at 80% LTV.
"""

import pytest

from radar.cash import (
    cash_scenario,
    check_eligibility,
    closing_costs,
    loan_amount,
    monthly_repayment,
    scenario_table,
    sooner_support,
)

PRICE = 2_000_000


# --- Loan ------------------------------------------------------------------

def test_bank_lends_on_the_lower_of_price_and_valuation():
    assert loan_amount(PRICE, 2_200_000) == pytest.approx(1_600_000)  # 80% of the price
    assert loan_amount(PRICE, 1_800_000) == pytest.approx(1_440_000)  # 80% of the valuation
    assert loan_amount(PRICE, PRICE, ltv=0.75) == pytest.approx(1_500_000)


# --- Closing costs ---------------------------------------------------------

def test_fee_lines_match_sooners_calculator_receipt():
    # Sooner's calculator, AED 3,000,000 home with an AED 2,400,000 loan.
    costs = closing_costs(3_000_000, loan=2_400_000)

    assert costs == pytest.approx({
        "Dubai Land Department": 120_580,  # 4% of price + 580
        "DLD title deed": 250,
        "Agency commission": 63_000,  # 2% of price + 5% VAT
        "Bank arrangement fee": 25_200,  # 1% of loan + 5% VAT
        "Mortgage registration": 6_010,  # 0.25% of loan + 10
        "Valuation": 3_150,  # 3,000 + 5% VAT
        "Trustee": 4_200,  # 4,000 + 5% VAT
        "NOC": 2_625,  # 2,500 + 5% VAT
        "Conveyancing": 7_875,  # 7,500 + 5% VAT
    })
    assert sum(costs.values()) == pytest.approx(232_890)  # Sooner's total


def test_fee_total_matches_sooners_faq():
    # joinsooner.com FAQ: "On a AED 2,000,000 home that comes to AED 161,490."
    assert sum(closing_costs(PRICE, loan=1_600_000).values()) == pytest.approx(161_490)


def test_no_vat_on_government_fees():
    costs = closing_costs(PRICE, loan=1_600_000)

    assert costs["Dubai Land Department"] == pytest.approx(80_580)  # 80,000 + 580, no VAT
    assert costs["Mortgage registration"] == pytest.approx(4_010)  # 4,000 + 10, no VAT
    assert costs["Agency commission"] == pytest.approx(42_000)  # 40,000 + VAT


# --- Sooner ----------------------------------------------------------------

def test_sooner_covers_closing_costs_up_to_its_limits():
    # Costs below 10% of value: all covered.
    assert sooner_support(150_000, PRICE, PRICE) == 150_000
    # 10% of a AED 1,000,000 home is the limit.
    assert sooner_support(150_000, 1_000_000, 1_000_000) == pytest.approx(100_000)
    # AED 500,000 cap.
    assert sooner_support(600_000, 10_000_000, 10_000_000) == 500_000


def test_sooner_value_basis_price_or_valuation():
    # Valuation of AED 1.4M: 10% is 140,000, below the 150,000 of costs.
    assert sooner_support(150_000, PRICE, 1_400_000, value_basis="price") == 150_000
    assert sooner_support(150_000, PRICE, 1_400_000, value_basis="valuation") == pytest.approx(140_000)


def test_unknown_value_basis_is_rejected():
    with pytest.raises(ValueError):
        sooner_support(150_000, PRICE, PRICE, value_basis="market")


def test_monthly_repayment_matches_sooners_published_examples():
    # FAQ: AED 161,490 at the best rate (7%) is "about AED 3,634 a month".
    assert monthly_repayment(161_490, fee_rate=0.07) == pytest.approx(3_633.53, abs=0.01)
    # Calculator: AED 232,890 at 7% is "~AED 5,240 / mo". 232,890 x 1.35 / 60 = 5,240.03
    assert monthly_repayment(232_890, fee_rate=0.07) == pytest.approx(5_240, abs=1)


# --- Cash at completion ----------------------------------------------------

def test_no_gap_buyer_only_needs_the_down_payment():
    s = cash_scenario("No gap", PRICE, valuation=PRICE)

    assert s.down_payment == pytest.approx(400_000)  # 20% of price
    assert s.closing_costs == pytest.approx(161_490)
    assert s.sooner_support == pytest.approx(161_490)  # under 10% of 2M, so all covered
    assert s.cash_needed == pytest.approx(400_000)


def test_valuation_10_percent_low_costs_the_buyer_160k_more():
    # Valuation 1.8M: loan 1.44M, so the down payment is 560,000 instead of 400,000.
    # Bank and registration fees shrink with the loan (fees 159,410), and Sooner covers them all.
    table = scenario_table(PRICE, {"Low": 1_800_000}, cash_available=500_000)
    low = table.iloc[0]

    assert low["loan"] == pytest.approx(1_440_000)
    assert low["closing_costs"] == pytest.approx(159_410)
    assert low["cash_needed"] == pytest.approx(560_000)
    assert low["extra_cash_from_gap"] == pytest.approx(160_000)  # 80% of the 200,000 gap
    assert low["shortfall"] == pytest.approx(60_000)  # 560,000 needed, 500,000 available


def test_a_high_valuation_causes_no_extra_cash():
    table = scenario_table(PRICE, {"High": 2_300_000}, cash_available=500_000)

    assert table.iloc[0]["extra_cash_from_gap"] == pytest.approx(0)
    assert table.iloc[0]["shortfall"] == 0


def test_valuation_basis_can_leave_fees_uncovered_after_a_deep_down_valuation():
    # Valuation 1.4M: loan 1.12M, down payment 880,000, closing costs 155,250.
    # On a valuation basis Sooner covers 10% of 1.4M = 140,000, leaving 15,250.
    by_price = cash_scenario("P25", PRICE, 1_400_000, value_basis="price")
    by_valuation = cash_scenario("P25", PRICE, 1_400_000, value_basis="valuation")

    assert by_price.cash_needed == pytest.approx(880_000)
    assert by_valuation.cash_needed == pytest.approx(895_250)


def test_fees_on_a_cheap_home_can_exceed_sooners_10_percent():
    # AED 500,000 home: fees 54,390 (the flat fees weigh more on a small price),
    # but Sooner covers at most 10% = 50,000, so the buyer pays 4,390 of them.
    s = cash_scenario("No gap", 500_000, 500_000)

    assert s.closing_costs == pytest.approx(54_390)
    assert s.sooner_support == pytest.approx(50_000)
    assert s.cash_needed == pytest.approx(100_000 + 4_390)


def test_monthly_repayment_is_on_the_amount_sooner_pays():
    s = cash_scenario("No gap", PRICE, PRICE, fee_rate=0.08)
    # 161,490 x (1 + 0.08 x 5) / 60
    assert s.monthly_repayment == pytest.approx(161_490 * 1.4 / 60)


# --- Eligibility -----------------------------------------------------------

def test_eligibility_price_band():
    assert check_eligibility(PRICE) is None
    assert check_eligibility(500_000) is None
    assert check_eligibility(4_500_000) is None
    assert "minimum" in check_eligibility(499_999)
    assert "maximum" in check_eligibility(4_500_001)
