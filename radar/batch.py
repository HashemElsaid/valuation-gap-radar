"""Batch mode: run the gap check on every deal in a pipeline CSV.

Columns (header case doesn't matter):

    deal_id, area, property_type, bedrooms, size_sqft, price, cash_available
    building (optional)

Every deal comes back as one row of the report. A deal that can't be assessed
(unknown area, too few comparable sales, a missing number) still gets a row,
with the reason in `notes`, so nothing silently drops out of the pipeline.
The report is sorted with the riskiest deals first.
"""

import pandas as pd

from radar import config
from radar.advisor import advisor_note
from radar.cash import check_eligibility, scenario_table
from radar.comps import estimate_value, gap_risk
from radar.etl import clean_area_name

REQUIRED_COLUMNS = ["deal_id", "area", "property_type", "bedrooms", "size_sqft", "price", "cash_available"]

REPORT_COLUMNS = [
    "deal_id", "area", "building", "property_type", "bedrooms", "size_sqft", "price", "cash_available",
    "risk", "risk_score", "price_vs_estimate", "estimate", "estimate_low", "estimate_high",
    "confidence", "comps", "comps_from",
    "extra_cash_median", "extra_cash_p25", "short_median", "short_p25", "monthly_repayment",
    "notes", "advisor_note",
]

# Names agents use that differ from DLD's.
AREA_SHORTHANDS = {
    "JVC": "Jumeirah Village Circle",
    "JVT": "Jumeirah Village Triangle",
    "JLT": "Jumeirah Lakes Towers",
    "JBR": "Jumeirah Beach Residence",
    "DOWNTOWN": "Downtown Dubai",
    "MARINA": "Dubai Marina",
    "ARABIAN RANCHES": "Arabian Ranches I",
}

PROPERTY_TYPES = {"apartment": "Apartment", "flat": "Apartment", "villa": "Villa", "townhouse": "Villa"}

RISK_ORDER = {"High": 0, "Medium": 1, "Low": 2, "Unknown": 3}


def read_deals(file) -> pd.DataFrame:
    """Read a pipeline CSV and check it has the columns we need."""
    deals = pd.read_csv(file, dtype=str)
    deals.columns = deals.columns.str.strip().str.lower()
    missing = [c for c in REQUIRED_COLUMNS if c not in deals.columns]
    if missing:
        raise ValueError(f"The CSV is missing these columns: {', '.join(missing)}")
    return deals


def _text(value) -> str:
    """The cell as trimmed text, or '' if it is blank."""
    return value.strip() if isinstance(value, str) else ""


def _number(value) -> float | None:
    """'1,250,000' or '1250000' -> 1250000.0. Blank or junk -> None."""
    try:
        return float(_text(value).replace(",", ""))
    except ValueError:
        return None


def _bedrooms(value) -> int | None:
    """'studio' -> 0, '2' -> 2. Anything else -> None."""
    if _text(value).lower() == "studio":
        return 0
    beds = _number(value)
    return int(beds) if beds is not None and beds >= 0 and beds.is_integer() else None


def match_area(name, known_areas) -> str | None:
    """Map what the user typed ('JVC', 'jumeirah village circle') to a DLD area name."""
    name = _text(name)
    if not name:
        return None
    candidate = AREA_SHORTHANDS.get(name.upper()) or clean_area_name(name)
    return candidate if candidate in known_areas else None


def match_building(name, sales: pd.DataFrame, area: str) -> str | None:
    """The building's name as DLD spells it, matched ignoring case and extra spaces."""
    key = " ".join(_text(name).split()).upper()
    if not key:
        return None
    projects = sales.loc[sales["area"] == area, "project"].dropna().unique()
    return next((p for p in projects if p.upper() == key), None)


def assess_deal(sales: pd.DataFrame, deal: dict, *, ltv: float, fee_rate: float, value_basis: str) -> dict:
    """Check one deal. Always returns a row; problems go in `notes`."""
    area = match_area(deal.get("area"), set(sales["area"]))
    property_type = PROPERTY_TYPES.get(_text(deal.get("property_type")).lower())
    bedrooms = _bedrooms(deal.get("bedrooms"))
    size_sqft, price, cash = (_number(deal.get(c)) for c in ("size_sqft", "price", "cash_available"))
    building = _text(deal.get("building"))
    row = {
        "deal_id": _text(deal.get("deal_id")),
        "area": area or _text(deal.get("area")),
        "building": building,
        "property_type": property_type or _text(deal.get("property_type")),
        "bedrooms": bedrooms,
        "size_sqft": size_sqft,
        "price": price,
        "cash_available": cash,
        "risk": "Unknown",
    }

    # 1. Inputs we can't work with.
    problems = []
    if area is None:
        problems.append(f"unknown area '{_text(deal.get('area'))}'")
    if property_type is None:
        problems.append("property type must be apartment or villa")
    if bedrooms is None:
        problems.append("bedrooms must be a whole number or 'studio'")
    if not size_sqft or size_sqft <= 0:
        problems.append("size_sqft must be a positive number")
    if not price or price <= 0:
        problems.append("price must be a positive number")
    if cash is None or cash < 0:
        problems.append("cash_available must be a number")
    if problems:
        return {**row, "notes": "Can't assess: " + "; ".join(problems)}

    # 2. The estimate.
    notes = []
    eligibility = check_eligibility(price)
    if eligibility:
        notes.append(eligibility)
    project = match_building(building, sales, area)
    if building and project is None:
        notes.append("building not found, used the whole area")
    size_sqm = size_sqft / config.SQFT_PER_SQM
    est = estimate_value(sales, area, property_type, bedrooms, size_sqm, project)
    if est is None:
        notes.append("too few comparable sales to estimate")
        return {**row, "notes": "; ".join(notes)}
    if project and est.basis == "area":
        notes.append(f"fewer than {config.MIN_PROJECT_COMPS} similar sales in the building, used the whole area")

    # 3. Risk and cash.
    risk = gap_risk(price, est)
    scenarios = scenario_table(price, est.valuations, cash, ltv=ltv, fee_rate=fee_rate, value_basis=value_basis)
    by_name = scenarios.set_index("name")
    return {
        **row,
        "building": project or building,
        "risk": risk.level,
        "risk_score": risk.score,
        "price_vs_estimate": risk.premium,
        "estimate": est.value_median,
        "estimate_low": est.value_p25,
        "estimate_high": est.value_p75,
        "confidence": est.confidence,
        "comps": est.n_comps,
        "comps_from": est.basis,
        "extra_cash_median": by_name.loc["Median", "extra_cash_from_gap"],
        "extra_cash_p25": by_name.loc["P25", "extra_cash_from_gap"],
        "short_median": by_name.loc["Median", "shortfall"],
        "short_p25": by_name.loc["P25", "shortfall"],
        "monthly_repayment": by_name.loc["Median", "monthly_repayment"],
        "notes": "; ".join(notes),
        "advisor_note": advisor_note(area=area, property_type=property_type, bedrooms=bedrooms,
                                     size_sqm=size_sqm, price=price, cash_available=cash,
                                     estimate=est, risk=risk, scenarios=scenarios),
    }


def pipeline_summary(report: pd.DataFrame) -> dict:
    """Headline numbers for the pipeline, counting only deals Sooner can fund.

    Deals outside Sooner's price range stay in the report (flagged in notes),
    but they don't count towards risk or deposits: Sooner wouldn't fund them.
    """
    assessed = report[report["risk"] != "Unknown"]
    eligible = assessed[assessed["price"].between(config.MIN_PRICE_AED, config.MAX_PRICE_AED)]
    could_fail = eligible[eligible["short_p25"] > 0]  # buyer short if the bank values low
    return {
        "deals": len(report),
        "assessed": len(assessed),
        "eligible": len(eligible),
        "high": int((eligible["risk"] == "High").sum()),
        "medium": int((eligible["risk"] == "Medium").sum()),
        "could_fail": len(could_fail),
        "short_total": float(could_fail["short_p25"].sum()),
        "deposits_at_risk": config.FORM_F_DEPOSIT_SHARE * float(could_fail["price"].sum()),
    }


def assess_deals(sales: pd.DataFrame, deals: pd.DataFrame,
                 ltv: float = config.DEFAULT_LTV,
                 fee_rate: float = config.SOONER_FEE_DEFAULT,
                 value_basis: str = config.SOONER_VALUE_BASIS_DEFAULT) -> pd.DataFrame:
    """One report row per deal, riskiest first. Ties keep the order of the CSV."""
    rows = [assess_deal(sales, deal, ltv=ltv, fee_rate=fee_rate, value_basis=value_basis)
            for deal in deals.to_dict("records")]
    report = pd.DataFrame(rows, columns=REPORT_COLUMNS)
    order = report["risk"].map(RISK_ORDER)
    return (report.assign(_order=order)
            .sort_values(["_order", "risk_score"], ascending=[True, False], kind="stable")
            .drop(columns="_order")
            .reset_index(drop=True))
