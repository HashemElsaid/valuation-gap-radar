"""Plain-English advisor note for one deal, in the words a mortgage adviser would use.

The note has up to four parts:
1. how the price compares with recent similar sales (per sqft, as Dubai quotes it)
2. what a low valuation would mean for the buyer's cash
3. what to do about it (Medium and High risk only; optional)
4. a warning when the estimate itself is uncertain (Low confidence only)

Words are kept plain on purpose: "typical" rather than "median", "low end"
rather than "P25", "similar sales" rather than "comps".
"""

import pandas as pd

from radar import config
from radar.comps import Estimate, GapRisk

# A price this far below the estimate usually means a typo in the inputs.
UNUSUALLY_LOW = -0.25


def describe_home(property_type: str, bedrooms: int) -> str:
    """'studio apartments', '2-bed apartments', '3-bed villas'."""
    kind = "apartments" if property_type == "Apartment" else "villas"
    return f"studio {kind}" if bedrooms == 0 else f"{bedrooms}-bed {kind}"


def aed(amount: float) -> str:
    return f"AED {amount:,.0f}"


def per_sqft(price_per_sqm: float) -> float:
    return price_per_sqm / config.SQFT_PER_SQM


def advisor_note(*, area: str, property_type: str, bedrooms: int, size_sqm: float,
                 price: float, cash_available: float, estimate: Estimate, risk: GapRisk,
                 scenarios: pd.DataFrame, include_actions: bool = True) -> str:
    """A few short paragraphs (Markdown) explaining the risk and the cash at stake.

    `include_actions=False` leaves out the "what to do" paragraph, for pages that
    show next steps separately.
    """
    home = describe_home(property_type, bedrooms)
    if estimate.basis == "project":
        place = f"{estimate.comps['project'].iloc[0]} ({area})"
    else:
        place = area
    paragraphs = []

    # 1. The price against recent sales.
    deal_psf = per_sqft(price / size_sqm)
    if estimate.recent_count >= config.MIN_COMPS:
        ref_psf = per_sqft(estimate.recent_ppsqm)
        when = f"in the last {config.RECENT_DAYS} days ({estimate.recent_count} sales)"
    else:
        ref_psf = per_sqft(estimate.ppsqm_median)
        when = f"over the past months ({estimate.n_comps:,} sales, recent ones weighted most)"
    diff = deal_psf / ref_psf - 1
    direction = "above" if diff >= 0 else "below"
    paragraphs.append(
        f"Similar {home} in {place} typically sold for **AED {ref_psf:,.0f} per sqft** {when}. "
        f"This price works out to AED {deal_psf:,.0f} per sqft, **{abs(diff):.0%} {direction}** that."
    )

    # 2. What a low valuation would cost the buyer.
    by_name = scenarios.set_index("name")
    typical, low = by_name.loc["Median"], by_name.loc["P25"]
    sentences = []
    if risk.level == "Low" and risk.premium <= 0:
        sentences.append("The price is at or below our estimate, so a low valuation looks unlikely.")
    elif risk.level == "Low":
        sentences.append("That is in line with what similar homes sell for, so a low valuation looks unlikely.")
    else:
        if typical["extra_cash_from_gap"] > 0:
            sentences.append(
                f"If the bank values it at the typical estimate ({aed(typical['valuation'])}), the buyer needs "
                f"**{aed(typical['extra_cash_from_gap'])} more cash** at completion; if it values at the low end "
                f"({aed(low['valuation'])}), **{aed(low['extra_cash_from_gap'])} more**."
            )
        else:
            sentences.append(
                f"At the typical estimate there is no gap, but if the bank values at the low end "
                f"({aed(low['valuation'])}) the buyer needs **{aed(low['extra_cash_from_gap'])} more cash** "
                f"at completion."
            )
        if typical["shortfall"] > 0:
            sentences.append(
                f"With {aed(cash_available)} available, they would be **{aed(typical['shortfall'])} short** at the "
                f"typical estimate and {aed(low['shortfall'])} short at the low end."
            )
        elif low["shortfall"] > 0:
            sentences.append(
                f"With {aed(cash_available)} available, they would be **{aed(low['shortfall'])} short** if the bank "
                f"values at the low end."
            )
        else:
            sentences.append(f"Their {aed(cash_available)} covers both cases.")
    paragraphs.append(" ".join(sentences))

    # 3. What to do (optional), or a warning about the inputs.
    if include_actions and risk.level == "High":
        paragraphs.append(
            "Before the Form F is signed, consider a bank pre-valuation, renegotiating the price, "
            "or a Form F clause that protects the deposit if the valuation comes in low."
        )
    elif include_actions and risk.level == "Medium":
        paragraphs.append("Worth confirming the buyer has this buffer before signing.")
    if risk.premium < UNUSUALLY_LOW:
        paragraphs.append(
            f"A price {abs(risk.premium):.0%} below similar sales is unusual: "
            "double-check the size, bedrooms and price."
        )

    # 4. How sure we are.
    if estimate.confidence == "Low":
        tip = " Choosing the building would sharpen it." if estimate.basis == "area" else ""
        paragraphs.append(
            f"We're not very sure here ({estimate.n_comps:,} similar sales, with prices that vary a lot), "
            f"so treat this as a rough guide.{tip}"
        )

    return "\n\n".join(paragraphs)
