"""Plain-English advisor note for one deal, in the words a mortgage adviser would use.

The note has up to four parts:
1. how the price compares with recent similar sales (per sqft, as Dubai quotes it)
2. what a low valuation would mean for the buyer's cash
3. what to do about it (Medium and High risk only)
4. a warning when the estimate itself is uncertain (Low confidence only)
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
                 scenarios: pd.DataFrame) -> str:
    """A few short paragraphs (Markdown) explaining the risk and the cash at stake."""
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
        f"Similar {home} in {place} sold for a median of **AED {ref_psf:,.0f} per sqft** {when}. "
        f"This price works out to AED {deal_psf:,.0f} per sqft, **{abs(diff):.0%} {direction}** that."
    )

    # 2. What a low valuation would cost the buyer.
    by_name = scenarios.set_index("name")
    median, low = by_name.loc["Median"], by_name.loc["P25"]
    sentences = []
    if risk.level == "Low" and risk.premium <= 0:
        sentences.append("The price is at or below our estimate, so a valuation gap looks unlikely.")
    elif risk.level == "Low":
        sentences.append("That is in line with what similar homes sell for, so a valuation gap looks unlikely.")
    else:
        if median["extra_cash_from_gap"] > 0:
            sentences.append(
                f"If the bank values it at the median estimate ({aed(median['valuation'])}), the buyer needs "
                f"**{aed(median['extra_cash_from_gap'])} more cash** at completion; at the low end of the "
                f"range ({aed(low['valuation'])}), **{aed(low['extra_cash_from_gap'])} more**."
            )
        else:
            sentences.append(
                f"At the median estimate there is no gap, but at the low end of the range "
                f"({aed(low['valuation'])}) the buyer needs **{aed(low['extra_cash_from_gap'])} more cash** "
                f"at completion."
            )
        if median["shortfall"] > 0:
            sentences.append(
                f"With {aed(cash_available)} available, they would be **{aed(median['shortfall'])} short** at the "
                f"median estimate and {aed(low['shortfall'])} short at the low end."
            )
        elif low["shortfall"] > 0:
            sentences.append(
                f"With {aed(cash_available)} available, they would be **{aed(low['shortfall'])} short** at the low end."
            )
        else:
            sentences.append(f"Their {aed(cash_available)} covers both cases.")
    paragraphs.append(" ".join(sentences))

    # 3. What to do.
    if risk.level == "High":
        paragraphs.append(
            "Before the Form F is signed, consider a bank pre-valuation, renegotiating the price, "
            "or a Form F clause that protects the deposit if the valuation comes in low."
        )
    elif risk.level == "Medium":
        paragraphs.append("Worth confirming the buyer has this buffer before signing.")
    elif risk.premium < UNUSUALLY_LOW:
        paragraphs.append(
            f"A price {abs(risk.premium):.0%} below similar sales is unusual: "
            "double-check the size, bedrooms and price."
        )

    # 4. How sure we are.
    if estimate.confidence == "Low":
        tip = " Choosing the building would sharpen it." if estimate.basis == "area" else ""
        paragraphs.append(
            f"Confidence is low ({estimate.n_comps:,} comparable sales, with prices spread widely), "
            f"so treat this as a rough guide.{tip}"
        )

    return "\n\n".join(paragraphs)
