# Valuation Gap Radar

UAE banks lend on the lower of the agreed price and their own valuation. When
the valuation comes in low, the buyer has to cover the gap in cash, and for a
cash-tight first-time buyer that can kill the deal. Valuation Gap Radar
estimates a Dubai home's likely valuation from real Dubai Land Department
sales, scores the risk of a gap before the buyer signs, and shows how much
extra cash they would need.

> Work in progress, built in seven steps. The full README (screenshots,
> assumptions, limitations) comes in step 7.

## Quick start

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1          # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

The app runs on the committed sample (`data/sample/`) out of the box. To use
the full data, download the DLD transactions CSV (see below) into `data/raw/`
and run the ETL:

```powershell
python -m radar.etl
```

## Data

Source: [DLD open data](https://dubailand.gov.ae/en/open-data/real-estate-data/),
Transactions tab, "Download as CSV". The page only offers the current year;
older years are meant to be on [data.dubai](https://data.dubai). Filters used:
Transaction Type = Sales, Registration type = Ready, Is Free Hold? = Yes,
Usage = Residential. The ETL re-applies these, then also removes:

- sale types other than a plain resale. "Delayed Sell" rows (off-plan
  contracts registered at handover) sell about 10% above resales of the same
  homes, so they would inflate the estimate
- offices, shops, hotel rooms and land plots
- sales of a share of a unit rather than the whole unit
- penthouses and other rows without a bedroom count
- prices below AED 5,000 or above AED 150,000 per sqm (typos and nominal transfers)

## How the estimate works

1. **Comparable sales:** same area, property type and bedrooms, with a size
   within 20%. If the building (project) has at least 5 such sales, only
   those are used.
2. **Recency:** each comp is weighted so that a sale 4 months old counts half
   as much as one from this week.
3. **Value range:** the weighted P25, median and P75 of comp price per sqm,
   times the home's size.
4. **Confidence:** High needs at least 10 comps with a spread
   ((P75 - P25) / median) of 15% or less. Medium needs at least 5 comps with a
   spread of 30% or less. Anything else is Low. Fewer than 3 comps means no
   estimate at all.
5. **Gap risk score:** how far the agreed price sits above the median
   estimate, plus a buffer of 3 points (Medium confidence) or 6 points (Low).
   Below 3% is Low risk, 3-10% is Medium, and 10% or more is High. At 80% LTV,
   a 10% gap means the buyer needs extra cash of about 8% of the price.

### Backtest

`python -m radar.backtest` estimates each sale from the last 60 days using
only earlier sales, then compares the estimate with the price actually paid:

| Confidence | Share of sales | Median error | Within ±10% | Inside P25–P75 |
|---|---:|---:|---:|---:|
| High | 32% | 5.8% | 74% | 43% |
| Medium | 43% | 7.8% | 59% | 50% |
| Low | 22% | 17.3% | 33% | 53% |
| No estimate | 3% | – | – | – |

Accuracy improves with confidence, and about half of real prices land inside
the P25–P75 range, as they should. Comps from the same building are about
twice as accurate as area-wide comps (5.8% vs 11.0% median error). These are
errors against sale prices: DLD does not publish bank valuations, so they
can't be checked directly.

## Cash scenarios

For a valuation at P25, the median and P75:

- **Loan** = LTV × min(price, valuation). LTV defaults to 80%.
- **Closing costs:** DLD 4% of price + AED 580 admin, agency 2% of price, bank
  arrangement 1% of loan, valuation AED 3,150, mortgage registration 0.25% of
  loan, notary AED 4,000. VAT of 5% applies to everything except DLD fees and
  mortgage registration, as stated on Sooner's site.
- **Sooner support** = min(closing costs, 10% of property value, AED 500,000).
  "Property value" can be the price or the valuation (still to be confirmed).
- **Cash needed at completion** = down payment (price − loan) + closing costs
  Sooner doesn't cover.
- **Extra cash from the gap** = cash needed in the scenario − cash needed if the
  bank valued the home at the agreed price.
- **Monthly repayment** = Sooner amount × (1 + yearly fee × 5) ÷ 60. This
  reproduces Sooner's published example (AED 161,490 at 7% ≈ AED 3,634 a month).

Worked example: a AED 1,000,000 one-bed in JVC with AED 250,000 of cash.

| Valuation | Cash needed | Extra from the gap | Short by |
|---|---:|---:|---:|
| P75: AED 1,065,421 | 200,000 | 0 | 0 |
| Median: AED 945,323 | 243,741 | 43,741 | 0 |
| P25: AED 772,800 | 381,760 | 181,760 | 131,760 |

Closing costs run from 8.8% of the price (AED 500k home) down to 7.3%
(AED 4.5M), so for eligible homes they stay under Sooner's 10% limit and
Sooner covers them in full. The gap therefore hits the buyer through the down
payment. Whether "property value" means price or valuation only matters after
a deep down-valuation, where 10% of the valuation drops below the fees: about
14% below price on a AED 500k home, 23% at AED 1M and 30% at AED 4.5M.

## Layout

```
radar/            core logic, plain Python with no UI code, so it is easy to test
  config.py       every assumption: fees, Sooner terms, eligibility, paths
  etl.py          raw DLD CSV -> clean sales table (data/processed/sales.parquet)
  comps.py        comparable sales -> value range, confidence, gap risk
  backtest.py     checks the estimates against real sale prices
  cash.py         loan, closing costs, Sooner support, cash needed per scenario
tests/            unit tests (pytest)
data/raw/         full DLD download (gitignored)
data/processed/   ETL output (gitignored)
data/sample/      small committed sample so the app runs without the download
```

## Build steps

1. Project setup (done)
2. ETL: clean DLD transactions into a compact Parquet file (done)
3. Comps engine: estimate the valuation range and gap risk (done)
4. Cash math and tests: closing costs, Sooner support, cash needed per scenario (done)
5. Streamlit UI
6. Batch mode: risk report for a CSV of pipeline deals
7. README and deployment
