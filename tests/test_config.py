"""Sanity checks on the assumptions, to catch typos before they reach the math."""

from radar import config


def test_fee_rates_look_like_percentages():
    # Every closing-cost rate is a few percent at most, so typing 0.25 (25%)
    # instead of 0.0025 (0.25%) fails here.
    rates = [
        config.DLD_RATE,
        config.AGENCY_RATE,
        config.BANK_ARRANGEMENT_RATE,
        config.MORTGAGE_REGISTRATION_RATE,
        config.VAT_RATE,
    ]
    for rate in rates:
        assert 0 < rate <= 0.05


def test_sooner_default_fee_is_inside_the_published_range():
    assert config.SOONER_FEE_MIN <= config.SOONER_FEE_DEFAULT <= config.SOONER_FEE_MAX


def test_price_band_is_valid():
    assert 0 < config.MIN_PRICE_AED < config.MAX_PRICE_AED


def test_value_basis_default_is_a_known_option():
    assert config.SOONER_VALUE_BASIS_DEFAULT in ("price", "valuation")
