"""Backtest: how well do comps predict real sale prices?

For each sale in the last 60 days of data, estimate its value using only the
sales registered before it, then compare the estimate with the price paid.

    python -m radar.backtest

Caveat: this measures how well we predict sale prices, not bank valuations.
DLD doesn't publish valuations next to sales, so the sale price is the closest
thing we can check against.
"""

import pandas as pd

from radar.comps import estimate_value, gap_risk
from radar.etl import load_sales

TEST_DAYS = 60
LEVELS = ["High", "Medium", "Low", "No estimate"]


def run(sales: pd.DataFrame, test_days: int = TEST_DAYS) -> pd.DataFrame:
    """One row per test sale: confidence, error vs the estimate, and risk level."""
    test = sales[sales["date"] > sales["date"].max() - pd.Timedelta(days=test_days)]
    rows = []
    for sale in test.itertuples():
        est = estimate_value(sales, sale.area, sale.property_type, sale.bedrooms, sale.size_sqm,
                             project=sale.project, as_of=sale.date - pd.Timedelta(days=1))
        if est is None:
            rows.append({"confidence": "No estimate"})
            continue
        rows.append({
            "confidence": est.confidence,
            "basis": est.basis,
            "error": sale.price_aed / est.value_median - 1,
            # 1.0/0.0 rather than True/False, so averaging works next to blanks
            "inside_range": float(est.value_p25 <= sale.price_aed <= est.value_p75),
            "risk": gap_risk(sale.price_aed, est).level,
        })
    return pd.DataFrame(rows)


def summarise(results: pd.DataFrame) -> pd.DataFrame:
    """Accuracy by confidence level. A good engine is more accurate at higher confidence."""
    groups = results.groupby("confidence")
    table = pd.DataFrame({
        "sales": groups.size(),
        "share": groups.size() / len(results),
        "median_abs_error": groups["error"].apply(lambda e: e.abs().median()),
        "within_10pct": groups["error"].apply(lambda e: (e.abs() <= 0.10).mean()),
        "inside_p25_p75": groups["inside_range"].mean(),
    })
    return table.reindex(LEVELS)


def main() -> None:
    sales = load_sales()
    results = run(sales)
    print(f"Backtest on {len(results):,} sales from the last {TEST_DAYS} days\n")
    table = summarise(results)
    print(table.to_string(formatters={
        "sales": "{:,.0f}".format,
        "share": "{:.0%}".format,
        "median_abs_error": "{:.1%}".format,
        "within_10pct": "{:.0%}".format,
        "inside_p25_p75": "{:.0%}".format,
    }, na_rep="-"))
    print("\nRisk level if each sale's own price were the agreed price:")
    print(results["risk"].value_counts(normalize=True).reindex(["Low", "Medium", "High"])
          .map("{:.0%}".format).to_string())


if __name__ == "__main__":
    main()
