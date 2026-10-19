"""ETL: turn the raw DLD transactions export into a clean table of sales.

Run it from the project root:

    python -m radar.etl

It reads every CSV in data/raw/, keeps plain resales of ready freehold
apartments and villas from the last 24 months, and writes two files:

- data/processed/sales.parquet         every clean sale (gitignored)
- data/sample/sales_sample.parquet     the busiest areas only (committed, so
                                       the app runs without the download)

Each filter prints how many rows it removed, so you can see exactly what
happened to the data.
"""

import pandas as pd

from radar import config

# Raw DLD column -> our name. Columns not listed here are dropped.
COLUMNS = {
    "TRANSACTION_NUMBER": "transaction_id",
    "INSTANCE_DATE": "date",
    "PROCEDURE_EN": "procedure",
    "IS_OFFPLAN_EN": "registration",
    "IS_FREE_HOLD_EN": "freehold",
    "USAGE_EN": "usage",
    "AREA_EN": "area",
    "PROJECT_EN": "project",
    "PROP_TYPE_EN": "dld_type",
    "PROP_SB_TYPE_EN": "dld_sub_type",
    "ROOMS_EN": "rooms",
    "PROCEDURE_AREA": "procedure_area",
    "ACTUAL_AREA": "size_sqm",
    "TRANS_VALUE": "price_aed",
}

# DLD (type, sub-type) -> our property type. Apartments are recorded as a
# "Unit" of sub-type "Flat"; villas as a "Building" of sub-type "Villa".
PROPERTY_TYPES = {
    ("Unit", "Flat"): "Apartment",
    ("Building", "Villa"): "Villa",
}

# DLD mixes official land names with community names, so one place can appear
# under two names. Each merge was checked against the projects listed under it
# (e.g. "Burj Khalifa" holds 29 Boulevard and Address Opera: Downtown Dubai).
AREA_ALIASES = {
    "Burj Khalifa": "Downtown Dubai",
    "Marsa Dubai": "Dubai Marina",
    "Hadaeq Sheikh Mohammed Bin Rashid": "Dubai Hills",
    "Emirate Living": "Emirates Living",
    "Sobha Heartland": "Sobha Hartland",
}

# Words that stay in capitals when area names are tidied.
KEEP_UPPER = {"I", "II", "III", "MBR", "PH", "TECOM", "DMCC-EZ2"}

OUTPUT_COLUMNS = [
    "transaction_id",
    "date",
    "area",
    "project",
    "property_type",
    "bedrooms",
    "size_sqm",
    "price_aed",
    "price_per_sqm",
]


def clean_area_name(name: str) -> str:
    """'JUMEIRAH VILLAGE CIRCLE' -> 'Jumeirah Village Circle', then apply aliases."""
    words = [w.upper() if w.upper() in KEEP_UPPER else w.capitalize() for w in name.split()]
    tidy = " ".join(words)
    return AREA_ALIASES.get(tidy, tidy)


def parse_bedrooms(rooms: pd.Series) -> pd.Series:
    """'Studio' -> 0, '2 B/R' -> 2. Anything else (Penthouse, Office, blank) -> missing."""
    rooms = rooms.str.strip()
    beds = pd.to_numeric(rooms.str.extract(r"^(\d+) B/R$", expand=False), errors="coerce")
    return beds.mask(rooms.eq("Studio"), 0)


def load_raw(raw_dir=config.RAW_DIR) -> pd.DataFrame:
    """Read every CSV in data/raw/ into one table (all columns as text)."""
    files = sorted(raw_dir.glob("*.csv"))
    if not files:
        raise FileNotFoundError(f"No CSV files in {raw_dir}. Download the DLD export first.")
    # utf-8-sig strips the byte-order mark DLD puts at the start of the file.
    frames = [pd.read_csv(f, dtype=str, encoding="utf-8-sig") for f in files]
    return pd.concat(frames, ignore_index=True)


def clean(raw: pd.DataFrame, verbose: bool = True) -> pd.DataFrame:
    """Filter and tidy raw DLD rows into one row per clean sale."""
    df = raw[list(COLUMNS)].rename(columns=COLUMNS)

    # Convert text to proper types. Anything unreadable becomes missing (NaN)
    # and is removed by the first rule below.
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
    for col in ["price_aed", "size_sqm", "procedure_area"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["price_per_sqm"] = df["price_aed"] / df["size_sqm"]
    df["bedrooms"] = parse_bedrooms(df["rooms"])
    df["property_type"] = [PROPERTY_TYPES.get(key) for key in zip(df["dld_type"], df["dld_sub_type"])]

    # Each rule says which rows to KEEP. They run in order.
    rules = [
        ("missing date, area, price or size",
         lambda d: d[["date", "area", "price_aed", "size_sqm"]].notna().all(axis=1)
         & (d["price_aed"] > 0) & (d["size_sqm"] > 0)),
        ("duplicate transaction",
         lambda d: ~d["transaction_id"].duplicated()),
        ("not a plain resale (delayed sell, lease-to-own, ...)",
         lambda d: d["procedure"].eq("Sale")),
        ("not ready, freehold and residential",
         lambda d: d["registration"].eq("Ready") & d["freehold"].eq("Free Hold")
         & d["usage"].eq("Residential")),
        ("not an apartment or villa",
         lambda d: d["property_type"].notna()),
        ("sale of a share, not the whole unit",
         lambda d: (d["procedure_area"] - d["size_sqm"]).abs() <= 0.01 * d["size_sqm"]),
        ("bedrooms unknown (penthouse, blank)",
         lambda d: d["bedrooms"].notna()),
        (f"older than {config.LOOKBACK_MONTHS} months",
         lambda d: d["date"] >= d["date"].max() - pd.DateOffset(months=config.LOOKBACK_MONTHS)),
        (f"price per sqm outside {config.MIN_PRICE_PER_SQM:,}-{config.MAX_PRICE_PER_SQM:,}",
         lambda d: d["price_per_sqm"].between(config.MIN_PRICE_PER_SQM, config.MAX_PRICE_PER_SQM)),
    ]
    for reason, rule in rules:
        keep = rule(df)
        if verbose:
            print(f"  {reason:<55} removed {(~keep).sum():>6,}   left {keep.sum():>6,}")
        df = df[keep]

    # Tidy the text columns and finish.
    df["area"] = df["area"].map(clean_area_name)
    df["project"] = df["project"].str.split().str.join(" ")  # collapse double spaces
    df["bedrooms"] = df["bedrooms"].astype(int)
    df["price_per_sqm"] = df["price_per_sqm"].round(0)
    return df[OUTPUT_COLUMNS].sort_values("date").reset_index(drop=True)


def build_sample(sales: pd.DataFrame, n_areas: int = config.SAMPLE_AREAS) -> pd.DataFrame:
    """Every sale in the busiest areas for each property type.

    Picking per type matters: the busiest areas overall are almost all
    apartment areas, which would leave the sample with hardly any villas.
    """
    parts = []
    for _, group in sales.groupby("property_type"):
        busiest = group["area"].value_counts().head(n_areas).index
        parts.append(group[group["area"].isin(busiest)])
    return pd.concat(parts).sort_values("date").reset_index(drop=True)


def load_sales() -> pd.DataFrame:
    """The full clean data if you've run the ETL, otherwise the committed sample."""
    path = config.PROCESSED_PATH if config.PROCESSED_PATH.exists() else config.SAMPLE_PATH
    return pd.read_parquet(path)


def main() -> None:
    raw = load_raw()
    print(f"Read {len(raw):,} rows from {config.RAW_DIR}")
    sales = clean(raw)

    sample = build_sample(sales)
    for frame, path in [(sales, config.PROCESSED_PATH), (sample, config.SAMPLE_PATH)]:
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path, index=False)
        print(f"Wrote {len(frame):,} sales to {path.relative_to(config.ROOT)} "
              f"({path.stat().st_size / 1024:,.0f} KB)")

    print(f"Dates {sales['date'].min():%d %b %Y} to {sales['date'].max():%d %b %Y}, "
          f"{sales['area'].nunique()} areas, {sales['project'].nunique():,} projects")


if __name__ == "__main__":
    main()
