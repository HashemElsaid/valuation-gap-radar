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
PROCESSED_PATH = ROOT / "data" / "processed" / "sales.parquet"  # ETL output, never committed
SAMPLE_PATH = ROOT / "data" / "sample" / "sales_sample.parquet"  # small, committed

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
# The comment on each line says what it is charged on.
# ---------------------------------------------------------------------------
DLD_RATE = 0.04  # of the price
DLD_ADMIN_AED = 580  # flat
AGENCY_RATE = 0.02  # of the price
BANK_ARRANGEMENT_RATE = 0.01  # of the loan
VALUATION_AED = 3_150  # flat
MORTGAGE_REGISTRATION_RATE = 0.0025  # of the loan
NOTARY_AED = 4_000  # flat
VAT_RATE = 0.05  # on agency, bank arrangement, valuation and notary; not on government fees

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
