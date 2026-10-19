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

## Layout

```
radar/            core logic, plain Python with no UI code, so it is easy to test
  config.py       every assumption: fees, Sooner terms, eligibility, paths
tests/            unit tests (pytest)
data/raw/         full DLD download (gitignored)
data/processed/   ETL output (gitignored)
data/sample/      small committed sample so the app runs without the download
```

## Build steps

1. Project setup (done)
2. ETL: clean DLD transactions into a compact Parquet file
3. Comps engine: estimate the valuation range and gap risk
4. Cash math and tests: closing costs, Sooner support, cash needed per scenario
5. Streamlit UI
6. Batch mode: risk report for a CSV of pipeline deals
7. README and deployment
