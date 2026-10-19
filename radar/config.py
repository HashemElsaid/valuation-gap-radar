"""Every assumption the app relies on, in one place.

Eligibility limits, Sooner's terms, closing fees and the comps window all live
here, so a reviewer can check them on one page and a change made here flows
through the whole app. The Streamlit UI uses these as defaults and lets the
user override the ones that are genuinely configurable (LTV, fee rate, value
basis).
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"  # full DLD CSV, never committed
PROCESSED_PATH = ROOT / "data" / "processed" / "sales.parquet"  # ETL output, all areas, committed
SAMPLE_PATH = ROOT / "data" / "sample" / "sales_sample.parquet"  # smaller fallback if the above is missing
EXAMPLE_PIPELINE_PATH = ROOT / "data" / "sample" / "pipeline_example.csv"  # for batch mode

# ---------------------------------------------------------------------------
# Homes Sooner covers: ready freehold property in Dubai within this price band
# ---------------------------------------------------------------------------
MIN_PRICE_AED = 500_000
MAX_PRICE_AED = 4_500_000

# ---------------------------------------------------------------------------
# Sooner's product
# ---------------------------------------------------------------------------
SOONER_MAX_SHARE = 0.10  # covers up to 10% of the property value...
SOONER_CAP_AED = 500_000  # ...and never more than AED 500,000
SOONER_TERM_MONTHS = 60
SOONER_FEE_MIN = 0.07  # flat fee per year on the amount advanced
SOONER_FEE_MAX = 0.09
SOONER_FEE_DEFAULT = 0.08

# Open question: is "property value" the agreed price or the bank valuation?
# The app can use either; "price" is the default until Sooner confirms.
SOONER_VALUE_BASIS_DEFAULT = "price"  # "price" or "valuation"

# ---------------------------------------------------------------------------
# Mortgage
# ---------------------------------------------------------------------------
# UAE Central Bank cap for an expat's first home under AED 5M.
DEFAULT_LTV = 0.80

# ---------------------------------------------------------------------------
# Closing costs (fee lines listed on joinsooner.com)
# The comment on each line says what it is charged on. Sooner's site doesn't
# say whether the bank and registration fees are on the price or the loan;
# UAE practice is the loan, so a low valuation makes them slightly smaller.
#
# Open question: these lines total about AED 150,900 on a AED 2M home, but
# Sooner's FAQ quotes AED 161,490 for the same home.
# ---------------------------------------------------------------------------
DLD_RATE = 0.04  # of the price
DLD_ADMIN_AED = 580  # flat
AGENCY_RATE = 0.02  # of the price
BANK_ARRANGEMENT_RATE = 0.01  # of the loan
VALUATION_AED = 3_150  # flat
MORTGAGE_REGISTRATION_RATE = 0.0025  # of the loan
NOTARY_AED = 4_000  # flat
# Sooner: "VAT applies to all except mortgage registration & land dept fees".
VAT_RATE = 0.05

# ---------------------------------------------------------------------------
# Market data and comparables
# ---------------------------------------------------------------------------
LOOKBACK_MONTHS = 24  # the ETL keeps sales from the last 24 months
SIZE_TOLERANCE = 0.20  # a comp's size must be within ±20% of the subject's

# Sales outside this price-per-sqm range are typos or non-market transfers.
# Even the cheapest freehold areas trade around AED 8,000-12,000 per sqm.
MIN_PRICE_PER_SQM = 5_000
MAX_PRICE_PER_SQM = 150_000

# The committed sample keeps every sale in this many of the busiest areas,
# chosen separately for apartments and villas.
SAMPLE_AREAS = 10

# ---------------------------------------------------------------------------
# Comps engine
# ---------------------------------------------------------------------------
MIN_COMPS = 3  # with fewer comps we don't estimate at all
MIN_PROJECT_COMPS = 5  # use same-project comps only when there are at least this many
RECENCY_HALF_LIFE_DAYS = 120  # a sale this many days old counts half as much as today's
RECENT_DAYS = 90  # window for the "sold in the last 90 days" figure

# Confidence: enough comps, agreeing closely. Spread = (P75 - P25) / median.
HIGH_CONFIDENCE_COMPS = 10
HIGH_CONFIDENCE_SPREAD = 0.15
MEDIUM_CONFIDENCE_COMPS = 5
MEDIUM_CONFIDENCE_SPREAD = 0.30

# Gap risk score = how far the price sits above the median estimate, plus a
# buffer when the estimate is less certain.
CONFIDENCE_BUFFER = {"High": 0.0, "Medium": 0.03, "Low": 0.06}
MEDIUM_RISK_FROM = 0.03  # score of 3% or more
HIGH_RISK_FROM = 0.10  # score of 10% or more

SQFT_PER_SQM = 10.7639  # Dubai agents quote prices per sqft
