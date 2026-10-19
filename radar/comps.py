"""Comps engine: estimate a home's likely valuation from similar recent sales,
and score the risk that the bank values it below the agreed price.

How it works:

1. Find comparable sales ("comps"): same area, property type and bedrooms,
   with a size within 20%. If enough of them are in the same project
   (building), use only those, as a valuer would.
2. Weight each comp by age, so recent sales count more.
3. Take the weighted 25th, 50th and 75th percentiles (P25, median, P75) of
   price per sqm and multiply by the home's size. That is the value range.
4. Rate confidence from how many comps there are and how closely they agree.
5. Score gap risk: how far the agreed price sits above the median estimate,
   plus a buffer when confidence is lower.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from radar import config


@dataclass
class Estimate:
    comps: pd.DataFrame  # the comparable sales used, newest first, with their weights
    basis: str  # "project" or "area": where the comps came from
    ppsqm_p25: float  # price per sqm
    ppsqm_median: float
    ppsqm_p75: float
    value_p25: float  # AED, for the subject home's size
    value_median: float
    value_p75: float
    spread: float  # (P75 - P25) / median: how much the comps disagree
    confidence: str  # "High", "Medium" or "Low"
    recent_ppsqm: float | None  # median price per sqm in the last 90 days, if any
    recent_count: int

    @property
    def n_comps(self) -> int:
        return len(self.comps)


@dataclass
class GapRisk:
    premium: float  # how far the price is above the median estimate (0.12 = 12%)
    buffer: float  # added when confidence is lower
    score: float  # premium + buffer
    level: str  # "Low", "Medium" or "High"


def find_comps(sales, area, property_type, bedrooms, size_sqm, project=None):
    """Return (comps, basis): same-project sales if there are enough, else the whole area."""
    low, high = size_sqm * (1 - config.SIZE_TOLERANCE), size_sqm * (1 + config.SIZE_TOLERANCE)
    similar = sales[
        (sales["area"] == area)
        & (sales["property_type"] == property_type)
        & (sales["bedrooms"] == bedrooms)
        & sales["size_sqm"].between(low, high)
    ]
    if isinstance(project, str) and project:  # skips None, blank and NaN
        same_project = similar[similar["project"] == project]
        if len(same_project) >= config.MIN_PROJECT_COMPS:
            return same_project, "project"
    return similar, "area"


def recency_weights(dates: pd.Series, as_of: pd.Timestamp) -> pd.Series:
    """1.0 for a sale on the as-of date, halving every RECENCY_HALF_LIFE_DAYS."""
    age_days = (as_of - dates).dt.days.clip(lower=0)
    return 0.5 ** (age_days / config.RECENCY_HALF_LIFE_DAYS)


def weighted_percentiles(values, weights, quantiles):
    """Percentiles where each value counts in proportion to its weight.

    Sort the values and lay their weights end to end along a line from 0 to 1.
    The 25th percentile is the value sitting at the 0.25 mark, and so on.
    """
    values = np.asarray(values, dtype=float)
    weights = np.asarray(weights, dtype=float)
    order = np.argsort(values)
    values, weights = values[order], weights[order]
    position = (np.cumsum(weights) - weights / 2) / weights.sum()  # centre of each slice
    return np.interp(quantiles, position, values)


def confidence_level(n_comps: int, spread: float) -> str:
    if n_comps >= config.HIGH_CONFIDENCE_COMPS and spread <= config.HIGH_CONFIDENCE_SPREAD:
        return "High"
    if n_comps >= config.MEDIUM_CONFIDENCE_COMPS and spread <= config.MEDIUM_CONFIDENCE_SPREAD:
        return "Medium"
    return "Low"


def estimate_value(sales, area, property_type, bedrooms, size_sqm, project=None, as_of=None):
    """Estimate the likely valuation range. Returns None if there are too few comps.

    `as_of` is the date the estimate is made on: only sales up to then are used,
    and recency is measured from it. It defaults to the newest sale in the data.
    """
    as_of = sales["date"].max() if as_of is None else pd.Timestamp(as_of)
    comps, basis = find_comps(sales[sales["date"] <= as_of], area, property_type,
                              bedrooms, size_sqm, project)
    if len(comps) < config.MIN_COMPS:
        return None

    comps = comps.assign(weight=recency_weights(comps["date"], as_of))
    p25, median, p75 = weighted_percentiles(comps["price_per_sqm"], comps["weight"], [0.25, 0.5, 0.75])
    spread = (p75 - p25) / median
    recent = comps[comps["date"] > as_of - pd.Timedelta(days=config.RECENT_DAYS)]

    return Estimate(
        comps=comps.sort_values("date", ascending=False),
        basis=basis,
        ppsqm_p25=p25,
        ppsqm_median=median,
        ppsqm_p75=p75,
        value_p25=p25 * size_sqm,
        value_median=median * size_sqm,
        value_p75=p75 * size_sqm,
        spread=spread,
        confidence=confidence_level(len(comps), spread),
        recent_ppsqm=recent["price_per_sqm"].median() if len(recent) else None,
        recent_count=len(recent),
    )


def gap_risk(price: float, estimate: Estimate) -> GapRisk:
    """Score the risk that the valuation comes in below the agreed price."""
    premium = price / estimate.value_median - 1
    buffer = config.CONFIDENCE_BUFFER[estimate.confidence]
    score = premium + buffer
    if score >= config.HIGH_RISK_FROM:
        level = "High"
    elif score >= config.MEDIUM_RISK_FROM:
        level = "Medium"
    else:
        level = "Low"
    return GapRisk(premium=premium, buffer=buffer, score=score, level=level)
