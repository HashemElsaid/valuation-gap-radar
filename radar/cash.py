"""Cash math: what the buyer has to pay at completion for a given valuation.

The key rule: UAE banks lend on the LOWER of the agreed price and the bank's
valuation. If the valuation comes in below the price, the loan shrinks and
the buyer has to cover the difference in cash.

For each valuation scenario this module works out:

- the loan: LTV x min(price, valuation)
- the down payment: price minus the loan
- closing costs, line by line (DLD, agency, bank fees, VAT, ...)
- Sooner's support: min(closing costs, 10% of the property value, AED 500,000)
- the cash needed at completion: down payment + closing costs Sooner doesn't cover
- the monthly Sooner repayment

This module knows nothing about comps: it takes valuations as plain numbers.
"""

from dataclasses import asdict, dataclass

import pandas as pd

from radar import config

VALUE_BASES = ("price", "valuation")


@dataclass
class CashScenario:
    name: str  # e.g. "P25", "Median", "P75"
    valuation: float
    loan: float
    down_payment: float  # price minus loan, paid in cash by the buyer
    closing_costs: float  # all fee lines including VAT
    sooner_support: float  # the part of closing costs Sooner pays
    cash_needed: float  # down payment + closing costs Sooner doesn't cover
    monthly_repayment: float  # repaying Sooner over 60 months


def check_eligibility(price: float) -> str | None:
    """A reason the home falls outside Sooner's price range, or None if it's eligible."""
    if price < config.MIN_PRICE_AED:
        return f"Below Sooner's minimum price of AED {config.MIN_PRICE_AED:,}"
    if price > config.MAX_PRICE_AED:
        return f"Above Sooner's maximum price of AED {config.MAX_PRICE_AED:,}"
    return None


def loan_amount(price: float, valuation: float, ltv: float = config.DEFAULT_LTV) -> float:
    """Banks lend on the lower of the price and the valuation."""
    return ltv * min(price, valuation)


def closing_costs(price: float, loan: float) -> dict[str, float]:
    """Each closing-cost line in AED, plus VAT on the lines it applies to."""
    lines = [
        # (fee line, amount, VAT applies?)
        ("DLD transfer fee", config.DLD_RATE * price, False),
        ("DLD admin fee", config.DLD_ADMIN_AED, False),
        ("Agency commission", config.AGENCY_RATE * price, True),
        ("Bank arrangement fee", config.BANK_ARRANGEMENT_RATE * loan, True),
        ("Bank valuation fee", config.VALUATION_AED, True),
        ("Mortgage registration", config.MORTGAGE_REGISTRATION_RATE * loan, False),
        ("Notary fee", config.NOTARY_AED, True),
    ]
    costs = {name: amount for name, amount, _ in lines}
    costs["VAT"] = config.VAT_RATE * sum(amount for _, amount, vat_applies in lines if vat_applies)
    return costs


def sooner_support(closing_total: float, price: float, valuation: float,
                   value_basis: str = config.SOONER_VALUE_BASIS_DEFAULT) -> float:
    """Sooner covers closing costs up to 10% of the property value, capped at AED 500,000.

    `value_basis` says which number counts as the "property value": the agreed
    price or the bank valuation (still to be confirmed with Sooner).
    """
    if value_basis not in VALUE_BASES:
        raise ValueError(f"value_basis must be one of {VALUE_BASES}, not {value_basis!r}")
    value = price if value_basis == "price" else valuation
    return min(closing_total, config.SOONER_MAX_SHARE * value, config.SOONER_CAP_AED)


def monthly_repayment(amount: float, fee_rate: float = config.SOONER_FEE_DEFAULT) -> float:
    """Flat fee: the yearly rate is charged on the original amount for every year.

    Over 60 months that is amount x (1 + rate x 5), split into 60 equal payments.
    """
    years = config.SOONER_TERM_MONTHS / 12
    return amount * (1 + fee_rate * years) / config.SOONER_TERM_MONTHS


def cash_scenario(name: str, price: float, valuation: float,
                  ltv: float = config.DEFAULT_LTV,
                  fee_rate: float = config.SOONER_FEE_DEFAULT,
                  value_basis: str = config.SOONER_VALUE_BASIS_DEFAULT) -> CashScenario:
    """The full cash picture at completion if the bank values the home at `valuation`."""
    loan = loan_amount(price, valuation, ltv)
    costs = sum(closing_costs(price, loan).values())
    support = sooner_support(costs, price, valuation, value_basis)
    return CashScenario(
        name=name,
        valuation=valuation,
        loan=loan,
        down_payment=price - loan,
        closing_costs=costs,
        sooner_support=support,
        cash_needed=(price - loan) + (costs - support),
        monthly_repayment=monthly_repayment(support, fee_rate),
    )


def scenario_table(price: float, valuations: dict[str, float], cash_available: float,
                   ltv: float = config.DEFAULT_LTV,
                   fee_rate: float = config.SOONER_FEE_DEFAULT,
                   value_basis: str = config.SOONER_VALUE_BASIS_DEFAULT) -> pd.DataFrame:
    """One row per valuation scenario, compared with a valuation at the full price.

    Adds two columns to each scenario:
    - extra_cash_from_gap: how much more cash the buyer needs than if the bank
      had valued the home at the agreed price
    - shortfall: how much more cash the buyer needs than they have (0 if enough)
    """
    settings = dict(ltv=ltv, fee_rate=fee_rate, value_basis=value_basis)
    no_gap = cash_scenario("No gap", price, price, **settings)
    rows = []
    for name, valuation in valuations.items():
        scenario = cash_scenario(name, price, valuation, **settings)
        rows.append({
            **asdict(scenario),
            "extra_cash_from_gap": scenario.cash_needed - no_gap.cash_needed,
            "shortfall": max(0.0, scenario.cash_needed - cash_available),
        })
    return pd.DataFrame(rows)
