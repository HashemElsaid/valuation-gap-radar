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

## Layout

```
radar/            core logic, plain Python with no UI code, so it is easy to test
  config.py       every assumption: fees, Sooner terms, eligibility, paths
  etl.py          raw DLD CSV -> clean sales table (data/processed/sales.parquet)
tests/            unit tests (pytest)
data/raw/         full DLD download (gitignored)
data/processed/   ETL output (gitignored)
data/sample/      small committed sample so the app runs without the download
```

## Build steps

1. Project setup (done)
2. ETL: clean DLD transactions into a compact Parquet file (done)
3. Comps engine: estimate the valuation range and gap risk
4. Cash math and tests: closing costs, Sooner support, cash needed per scenario
5. Streamlit UI
6. Batch mode: risk report for a CSV of pipeline deals
7. README and deployment
