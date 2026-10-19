"""Valuation Gap Radar: the Streamlit app.

Run it from the project root:

    streamlit run app.py

Two modes, picked at the top of the sidebar: check one deal, or upload a
pipeline CSV and check every deal in it. All the maths lives in the radar/
package. This file only collects inputs and shows results.
The app shows sizes and prices per sqft, as Dubai listings do; the engine
works in sqm, so the conversion happens here at the edge.
"""

import altair as alt
import pandas as pd
import streamlit as st

from radar import config
from radar.advisor import advisor_note, aed, describe_home, per_sqft
from radar.batch import REQUIRED_COLUMNS, assess_deals, read_deals
from radar.cash import check_eligibility, closing_costs, loan_amount, scenario_table
from radar.comps import estimate_value, find_comps, gap_risk
from radar.etl import load_sales

st.set_page_config(page_title="Valuation Gap Radar", page_icon=":material/radar:", layout="wide")

# Chart colours, checked for colour-blind safety against Streamlit's light and
# dark backgrounds. Text uses ink colours, never the data colours.
COLORS = {
    "light": {"comps": "#2a78d6", "deal": "#eb6834", "surface": "#ffffff", "ink": "#52514e"},
    "dark": {"comps": "#3987e5", "deal": "#d95926", "surface": "#0e1117", "ink": "#c3c2b7"},
}

# Each risk level gets a coloured box with its own icon, so colour is never the only cue.
RISK_BOX = {
    "Low": (st.success, ":material/check_circle:"),
    "Medium": (st.warning, ":material/warning:"),
    "High": (st.error, ":material/error:"),
}

SCENARIO_NAMES = {"P25": "Low valuation (P25)", "Median": "Median valuation", "P75": "High valuation (P75)"}

SCENARIO_ROWS = {
    "Bank valuation": "valuation",
    "Loan": "loan",
    "Down payment": "down_payment",
    "Closing costs": "closing_costs",
    "Paid by Sooner": "sooner_support",
    "Cash needed at completion": "cash_needed",
    "Extra cash caused by the gap": "extra_cash_from_gap",
    "Short by": "shortfall",
    "Monthly repayment to Sooner": "monthly_repayment",
}


@st.cache_data
def get_sales() -> pd.DataFrame:
    return load_sales()


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

def deal_inputs(sales: pd.DataFrame) -> dict:
    """Sidebar: the deal and the settings. Dropdowns only offer what has sales."""
    sb = st.sidebar
    sb.header("The deal")

    area_counts = sales["area"].value_counts()
    areas = sorted(area_counts.index)
    area = sb.selectbox("Area", areas, index=areas.index(area_counts.index[0]),
                        format_func=lambda a: f"{a} ({area_counts[a]:,} sales)")

    in_area = sales[sales["area"] == area]
    types = sorted(in_area["property_type"].unique())
    property_type = sb.segmented_control("Property type", types, default=types[0], required=True)

    of_type = in_area[in_area["property_type"] == property_type]
    bed_counts = of_type["bedrooms"].value_counts().sort_index()
    bedrooms = sb.selectbox("Bedrooms", bed_counts.index, index=int(bed_counts.argmax()),
                            format_func=lambda b: f"{'Studio' if b == 0 else b} ({bed_counts[b]:,} sales)")

    homes = of_type[of_type["bedrooms"] == bedrooms]
    project_counts = homes["project"].value_counts()
    project = sb.selectbox(
        "Building (optional)", [None, *project_counts.index],
        format_func=lambda p: "Any building in the area" if p is None else f"{p} ({project_counts[p]} sales)",
        help="Naming the building usually makes the estimate much more accurate.",
    )

    size_sqft = sb.number_input("Size (sqft)", min_value=150, max_value=30_000, value=750, step=10)
    typical = homes["size_sqm"].median() * config.SQFT_PER_SQM
    sb.caption(f"Typical size for {describe_home(property_type, bedrooms)} here: {typical:,.0f} sqft")
    price = sb.number_input("Agreed price (AED)", min_value=100_000, value=1_000_000, step=10_000)
    cash = sb.number_input("Cash the buyer has available (AED)", min_value=0, value=250_000, step=5_000)

    return {
        "area": area,
        "property_type": property_type,
        "bedrooms": int(bedrooms),
        "project": project,
        "size_sqm": size_sqft / config.SQFT_PER_SQM,
        "price": float(price),
        "cash_available": float(cash),
    }


def settings_inputs() -> dict:
    """Sidebar: the assumptions that apply to every deal, in both modes."""
    with st.sidebar.expander("Settings"):
        ltv = st.slider("Loan-to-value (%)", 50, 85, round(config.DEFAULT_LTV * 100), 5)
        # round() because 0.07 * 100 is 7.000000000000001 in floating point
        fee = st.slider("Sooner yearly fee (%)", round(config.SOONER_FEE_MIN * 100, 1),
                        round(config.SOONER_FEE_MAX * 100, 1), round(config.SOONER_FEE_DEFAULT * 100, 1), 0.5)
        value_basis = st.radio("Sooner's 10% limit is based on", ["price", "valuation"],
                               format_func=str.capitalize, help="Still to be confirmed with Sooner.")
    return {"ltv": ltv / 100, "fee_rate": fee / 100, "value_basis": value_basis}


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

def show_deal(sales: pd.DataFrame, d: dict, settings: dict) -> None:
    issue = check_eligibility(d["price"])
    if issue:
        st.warning(f"{issue}, so this deal isn't eligible for Sooner. The estimate below still applies.")

    home = (d["area"], d["property_type"], d["bedrooms"], d["size_sqm"])
    est = estimate_value(sales, *home, project=d["project"])
    if est is None:
        found, _ = find_comps(sales, *home)
        st.info(
            f"Not enough comparable sales to estimate a value: found {len(found)} "
            f"{describe_home(d['property_type'], d['bedrooms'])} in {d['area']} within "
            f"{config.SIZE_TOLERANCE:.0%} of this size (need {config.MIN_COMPS}). "
            "Try a size closer to the typical one shown in the sidebar.",
            icon=":material/search_off:",
        )
        return

    risk = gap_risk(d["price"], est)
    scenarios = scenario_table(d["price"], est.valuations, d["cash_available"], **settings)

    # Headline and advisor note
    box, icon = RISK_BOX[risk.level]
    direction = "above" if risk.premium >= 0 else "below"
    note = advisor_note(area=d["area"], property_type=d["property_type"], bedrooms=d["bedrooms"],
                        size_sqm=d["size_sqm"], price=d["price"], cash_available=d["cash_available"],
                        estimate=est, risk=risk, scenarios=scenarios)
    box(f"#### {risk.level} gap risk\nThe agreed price is {abs(risk.premium):.0%} {direction} our "
        f"estimate of {aed(est.value_median)}.\n\n{note}", icon=icon)

    # Key numbers, kept short so the tiles fit side by side on a laptop screen
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Estimate", aed_short(est.value_median), border=True)
    c1.caption(f"Likely range {aed(est.value_p25)} to {aed(est.value_p75)}")
    c2.metric("Price vs estimate", f"{risk.premium:+.1%}", border=True)
    c2.caption(f"Risk score {risk.score:+.1%}, including a {risk.buffer:.0%} buffer for confidence")
    c3.metric("Confidence", est.confidence, border=True)
    c3.caption(f"{est.n_comps:,} comparable sales, spread {est.spread:.0%}")
    c4.metric("Comps from", "Building" if est.basis == "project" else "Area", border=True)
    if d["project"] and est.basis == "area":
        c4.caption(f"Fewer than {config.MIN_PROJECT_COMPS} similar sales in {d['project']}, so the whole area was used")
    else:
        c4.caption(est.comps["project"].iloc[0] if est.basis == "project" else d["area"])

    # Cash scenarios
    st.subheader("Cash the buyer needs at completion")
    table = scenarios.set_index("name")[list(SCENARIO_ROWS.values())].T
    table.index = list(SCENARIO_ROWS)
    table = table.rename(columns=SCENARIO_NAMES)
    st.table(table.style.format("AED {:,.0f}"))
    st.caption(
        f"Loan = {settings['ltv']:.0%} of the lower of price and valuation. Sooner pays closing costs up to "
        f"{config.SOONER_MAX_SHARE:.0%} of the {settings['value_basis']} (max {aed(config.SOONER_CAP_AED)}), "
        f"repaid over {config.SOONER_TERM_MONTHS} months with a flat yearly fee of {settings['fee_rate']:.1%}."
    )
    with st.expander("Closing cost lines (if the bank values the home at the price)"):
        costs = closing_costs(d["price"], loan_amount(d["price"], d["price"], settings["ltv"]))
        lines = pd.Series(costs, name="AED").to_frame()
        lines.loc["Total"] = sum(costs.values())
        st.table(lines.style.format("AED {:,.0f}"))

    # Comparable sales
    st.subheader("Comparable sales")
    theme = st.context.theme.type or "light"
    st.altair_chart(price_chart(est, per_sqft(d["price"] / d["size_sqm"]), COLORS[theme]), width="stretch")
    st.caption(
        "Each dot is a sale. Fainter dots are older and count less. The shaded band is the likely "
        "range (P25 to P75)."
    )
    comps_table(est.comps)


def aed_short(amount: float) -> str:
    """AED 941k, AED 1.06M: short enough for a metric tile."""
    if amount >= 1_000_000:
        return f"AED {amount / 1_000_000:.2f}M"
    return f"AED {amount / 1_000:,.0f}k"


def price_chart(est, deal_psf: float, colors: dict) -> alt.Chart:
    """Comparable sales over time, with the likely range, the median and this deal.

    The two reference lines are named in a legend above the chart rather than
    labelled on the plot, because in busy areas the dots would bury the labels.
    """
    comps = est.comps.assign(
        price_per_sqft=lambda c: (c["price_per_sqm"] / config.SQFT_PER_SQM).round(0),
        size_sqft=lambda c: (c["size_sqm"] * config.SQFT_PER_SQM).round(0),
    )
    p25, median, p75 = (per_sqft(x) for x in (est.ppsqm_p25, est.ppsqm_median, est.ppsqm_p75))

    band = alt.Chart(pd.DataFrame({"p25": [p25], "p75": [p75]})).mark_rect(
        color=colors["comps"], opacity=0.10
    ).encode(y="p25:Q", y2="p75:Q")

    dots = alt.Chart(comps).mark_circle(
        size=70, color=colors["comps"], stroke=colors["surface"], strokeWidth=2
    ).encode(
        x=alt.X("date:T", title="Sale date"),
        y=alt.Y("price_per_sqft:Q", title="AED per sqft", scale=alt.Scale(zero=False),
                axis=alt.Axis(format=",.0f")),
        opacity=alt.Opacity("weight:Q", scale=alt.Scale(domain=[0, 1], range=[0.15, 0.8]), legend=None),
        tooltip=[
            alt.Tooltip("date:T", title="Date", format="%d %b %Y"),
            alt.Tooltip("project:N", title="Building"),
            alt.Tooltip("size_sqft:Q", title="Size (sqft)", format=",.0f"),
            alt.Tooltip("price_aed:Q", title="Price (AED)", format=",.0f"),
            alt.Tooltip("price_per_sqft:Q", title="AED per sqft", format=",.0f"),
            alt.Tooltip("weight:Q", title="Weight", format=".0%"),
        ],
    )

    refs = pd.DataFrame({
        "value": [median, deal_psf],
        "label": [f"Median of comparables: AED {median:,.0f}/sqft", f"This deal: AED {deal_psf:,.0f}/sqft"],
    })
    rules = alt.Chart(refs).mark_rule(strokeWidth=2).encode(
        y="value:Q",
        color=alt.Color("label:N", title=None,
                        scale=alt.Scale(domain=refs["label"].tolist(), range=[colors["comps"], colors["deal"]]),
                        legend=alt.Legend(orient="top", symbolType="stroke", labelColor=colors["ink"],
                                          labelLimit=400)),
    )
    return alt.layer(band, dots, rules).properties(height=360)


def comps_table(comps: pd.DataFrame) -> None:
    table = comps.assign(
        size_sqft=(comps["size_sqm"] * config.SQFT_PER_SQM).round(0),
        price_per_sqft=(comps["price_per_sqm"] / config.SQFT_PER_SQM).round(0),
    )[["date", "project", "bedrooms", "size_sqft", "price_aed", "price_per_sqft", "weight"]]
    with st.expander(f"All {len(table):,} comparable sales"):
        st.dataframe(table, hide_index=True, width="stretch", column_config={
            "date": st.column_config.DateColumn("Date", format="D MMM YYYY"),
            "project": "Building",
            "bedrooms": "Beds",
            "size_sqft": st.column_config.NumberColumn("Size (sqft)", format="localized"),
            "price_aed": st.column_config.NumberColumn("Price (AED)", format="localized"),
            "price_per_sqft": st.column_config.NumberColumn("AED per sqft", format="localized"),
            "weight": st.column_config.ProgressColumn("Weight", min_value=0, max_value=1, format="percent"),
        })


# ---------------------------------------------------------------------------
# Pipeline (batch) mode
# ---------------------------------------------------------------------------

REPORT_VIEW = {
    "deal_id": "Deal",
    "risk": "Risk",
    "area": "Area",
    "building": "Building",
    "property_type": "Type",
    "bedrooms": st.column_config.NumberColumn("Beds", format="%d"),
    "price": st.column_config.NumberColumn("Price (AED)", format="localized"),
    "estimate": st.column_config.NumberColumn("Estimate (AED)", format="localized"),
    "price_vs_estimate": st.column_config.NumberColumn("vs estimate", format="percent"),
    "confidence": "Confidence",
    "extra_cash_median": st.column_config.NumberColumn("Extra cash at median", format="localized"),
    "short_median": st.column_config.NumberColumn("Short at median", format="localized"),
    "short_p25": st.column_config.NumberColumn("Short at P25", format="localized"),
    "notes": "Notes",
}

MONEY_COLUMNS = ["price", "estimate", "extra_cash_median", "short_median", "short_p25"]


def show_batch(sales: pd.DataFrame, settings: dict) -> None:
    st.subheader("Check a pipeline of deals")
    st.caption(f"One deal per row. Columns: {', '.join(REQUIRED_COLUMNS)}, and optionally building. "
               "Sizes in sqft; bedrooms can be 'studio'. Area shorthands like JVC, JLT and Marina work.")
    left, right = st.columns([3, 1], vertical_alignment="bottom")
    upload = left.file_uploader("Pipeline CSV", type="csv")
    right.download_button("Example CSV", config.EXAMPLE_PIPELINE_PATH.read_bytes(),
                          file_name="pipeline_example.csv", mime="text/csv", icon=":material/download:")
    if upload is None:
        st.info("No file uploaded yet, so this is the example pipeline.", icon=":material/info:")

    try:
        deals = read_deals(upload or config.EXAMPLE_PIPELINE_PATH)
    except ValueError as error:  # also covers unreadable files: pandas' parse errors are ValueErrors
        st.error(f"Couldn't read the CSV. {error}", icon=":material/error:")
        return
    with st.spinner(f"Checking {len(deals):,} deals..."):
        report = assess_deals(sales, deals, **settings)
    assessed = report[report["risk"] != "Unknown"]

    # Summary
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Deals", len(report), border=True)
    c1.caption(f"{len(assessed)} assessed, {len(report) - len(assessed)} couldn't be")
    c2.metric("High risk", int((report["risk"] == "High").sum()), border=True)
    c2.caption(f"{int((report['risk'] == 'Medium').sum())} more at Medium risk")
    short = assessed[assessed["short_median"] > 0]
    c3.metric("Short at median", len(short), border=True)
    c3.caption(f"Buyers who'd lack cash if valued at the median: {aed(short['short_median'].sum())} in total")
    short_p25 = assessed[assessed["short_p25"] > 0]
    c4.metric("Short at P25", len(short_p25), border=True)
    c4.caption(f"If valued at the low end: {aed(short_p25['short_p25'].sum())} in total")

    # Report, riskiest first
    view = report[list(REPORT_VIEW)].round({c: 0 for c in MONEY_COLUMNS})
    st.dataframe(view, hide_index=True, width="stretch", column_config=REPORT_VIEW)
    st.download_button("Download full report (CSV)", report.to_csv(index=False).encode("utf-8"),
                       file_name="valuation_gap_report.csv", mime="text/csv", icon=":material/download:")

    # One deal's advisor note
    if assessed.empty:
        return
    st.subheader("Advisor note")
    pick = st.selectbox("Deal", assessed.index,
                        format_func=lambda i: f"{assessed.at[i, 'deal_id']}: {assessed.at[i, 'risk']} risk, "
                                              f"{assessed.at[i, 'area']}")
    row = assessed.loc[pick]
    box, icon = RISK_BOX[row["risk"]]
    box(f"#### {row['deal_id']}: {row['risk']} gap risk\n\n{row['advisor_note']}", icon=icon)


def data_footer(sales: pd.DataFrame) -> None:
    source = ("full DLD data" if config.PROCESSED_PATH.exists()
              else f"sample data (the {config.SAMPLE_AREAS} busiest areas for apartments and for villas)")
    st.divider()
    st.caption(
        f"Based on {len(sales):,} DLD sales of ready freehold homes, "
        f"{sales['date'].min():%d %b %Y} to {sales['date'].max():%d %b %Y} ({source}). "
        "This is an estimate from past sales, not a bank valuation."
    )


def main() -> None:
    sales = get_sales()
    st.title("Valuation Gap Radar")
    st.caption("Before the buyer signs: will the bank value this home below the agreed price, "
               "and how much extra cash would that take?")
    mode = st.sidebar.segmented_control("Check", ["One deal", "Pipeline CSV"], default="One deal", required=True)
    if mode == "One deal":
        deal = deal_inputs(sales)
        settings = settings_inputs()
        show_deal(sales, deal, settings)
    else:
        settings = settings_inputs()
        show_batch(sales, settings)
    data_footer(sales)


main()
