"""Valuation Gap Radar: the Streamlit app.

Run it from the project root:

    streamlit run app.py

Two modes, picked at the top of the sidebar: check one deal, or upload a
pipeline CSV and check every deal in it. All the maths lives in the radar/
package. This file only collects inputs and shows results.
The app shows sizes and prices per sqft, as Dubai listings do; the engine
works in sqm, so the conversion happens here at the edge.

Colours and fonts are set in .streamlit/config.toml.
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

# Chart colours, checked for colour-blind safety against the light and dark
# backgrounds: comparable sales are blue, this deal is orange. Text uses ink
# colours, never the data colours.
COLORS = {
    "light": {"comps": "#2a78d6", "deal": "#eb6834", "surface": "#ffffff",
              "ink": "#14213d", "muted": "#5b6475", "bad": "#a82828"},
    "dark": {"comps": "#3987e5", "deal": "#d95926", "surface": "#0e1117",
             "ink": "#e8eaee", "muted": "#a9b0bc", "bad": "#ff8a8a"},
}

# Each risk level has a badge colour and its own icon, so colour is never the only cue.
RISK_STYLE = {
    "Low": ("green", ":material/check_circle:"),
    "Medium": ("yellow", ":material/warning:"),
    "High": ("red", ":material/error:"),
}
RISK_TINT = {  # see-through, so it works on light and dark backgrounds
    "High": "background-color: rgba(208, 59, 59, 0.16)",
    "Medium": "background-color: rgba(250, 178, 25, 0.20)",
    "Low": "background-color: rgba(12, 163, 12, 0.13)",
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


def colors() -> dict:
    return COLORS[st.context.theme.type or "light"]


def aed_short(amount: float) -> str:
    """AED 941k, AED 1.06M: short enough for a tile or a chart label."""
    if amount >= 1_000_000:
        return f"AED {amount / 1_000_000:.2f}M"
    if amount >= 1_000:
        return f"AED {amount / 1_000:,.0f}k"
    return f"AED {amount:,.0f}"


def home_label(property_type: str, bedrooms: int) -> str:
    """'Studio apartment', '2-bed apartment', '3-bed villa'."""
    kind = property_type.lower()
    return f"Studio {kind}" if bedrooms == 0 else f"{bedrooms}-bed {kind}"


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def sidebar_header() -> str:
    """App name, purpose and the mode switch. Returns the chosen mode."""
    sb = st.sidebar
    sb.markdown("### :material/radar: Valuation Gap Radar")
    sb.caption("Spot down-valuation risk before the buyer signs the Form F.")
    # ?mode=pipeline in the URL opens pipeline mode directly, e.g. for a shared link.
    default_mode = "Pipeline CSV" if st.query_params.get("mode") == "pipeline" else "One deal"
    return sb.segmented_control("Mode", ["One deal", "Pipeline CSV"], default=default_mode, required=True,
                                label_visibility="collapsed", width="stretch")


def deal_inputs(sales: pd.DataFrame) -> dict:
    """The home and the deal. Dropdowns only offer what has sales, with counts."""
    sb = st.sidebar
    sb.subheader("The home")
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
    sb.caption(f"Typical here: {typical:,.0f} sqft")

    sb.subheader("The deal")
    price = sb.number_input("Agreed price (AED)", min_value=100_000, value=1_000_000, step=10_000)
    sb.caption(aed(price))  # number inputs can't show thousands separators, so repeat it here
    cash = sb.number_input("Buyer's cash available (AED)", min_value=0, value=250_000, step=5_000)
    sb.caption(f"{aed(cash)} for the down payment and any gap")

    return {
        "area": area,
        "property_type": property_type,
        "bedrooms": int(bedrooms),
        "project": project,
        "size_sqft": float(size_sqft),
        "size_sqm": size_sqft / config.SQFT_PER_SQM,
        "price": float(price),
        "cash_available": float(cash),
    }


def settings_inputs() -> dict:
    """The assumptions that apply to every deal, in both modes."""
    with st.sidebar.expander("Assumptions", icon=":material/tune:"):
        ltv = st.slider("Loan-to-value (%)", 50, 85, round(config.DEFAULT_LTV * 100), 5)
        # round() because 0.07 * 100 is 7.000000000000001 in floating point
        fee = st.slider("Sooner yearly fee (%)", round(config.SOONER_FEE_MIN * 100, 1),
                        round(config.SOONER_FEE_MAX * 100, 1), round(config.SOONER_FEE_DEFAULT * 100, 1), 0.5)
        value_basis = st.radio("Sooner's 10% limit is based on", ["price", "valuation"],
                               format_func=str.capitalize, help="Still to be confirmed with Sooner.")
    return {"ltv": ltv / 100, "fee_rate": fee / 100, "value_basis": value_basis}


# ---------------------------------------------------------------------------
# One deal
# ---------------------------------------------------------------------------

def show_deal(sales: pd.DataFrame, d: dict, settings: dict) -> None:
    building = d["project"] or "Any building"
    st.header(f"{home_label(d['property_type'], d['bedrooms'])} in {d['area']}")
    st.caption(f"{d['size_sqft']:,.0f} sqft · {building} · Agreed price {aed(d['price'])} · "
               f"Buyer's cash {aed(d['cash_available'])}")

    issue = check_eligibility(d["price"])
    if issue:
        st.warning(f"{issue}, so this deal isn't eligible for Sooner. The estimate below still applies.",
                   icon=":material/info:")

    home = (d["area"], d["property_type"], d["bedrooms"], d["size_sqm"])
    est = estimate_value(sales, *home, project=d["project"])
    if est is None:
        no_estimate(sales, d, home)
        return

    risk = gap_risk(d["price"], est)
    scenarios = scenario_table(d["price"], est.valuations, d["cash_available"], **settings)
    note = advisor_note(area=d["area"], property_type=d["property_type"], bedrooms=d["bedrooms"],
                        size_sqm=d["size_sqm"], price=d["price"], cash_available=d["cash_available"],
                        estimate=est, risk=risk, scenarios=scenarios)

    verdict_card(d, est, risk, scenarios)
    note_card(note)

    cash_tab, comps_tab, costs_tab = st.tabs([
        ":material/payments: Cash at completion",
        ":material/scatter_plot: Comparable sales",
        ":material/receipt_long: Closing costs",
    ])
    with cash_tab:
        cash_table(scenarios, settings)
    with comps_tab:
        comparable_sales(est, d)
    with costs_tab:
        closing_cost_lines(d, settings)


def verdict_card(d: dict, est, risk, scenarios: pd.DataFrame) -> None:
    """The answer first: risk level, where the price sits, and the cash at stake."""
    color, icon = RISK_STYLE[risk.level]
    by_name = scenarios.set_index("name")
    low, median = by_name.loc["P25"], by_name.loc["Median"]
    direction = "above" if risk.premium >= 0 else "below"

    with st.container(border=True):
        st.badge(f"{risk.level} gap risk", color=color, icon=icon)
        st.markdown(f"### The agreed price is {abs(risk.premium):.0%} {direction} our estimate "
                    f"of {aed(est.value_median)}")
        if risk.buffer:
            st.caption(f"Risk score {risk.score:+.1%}: the {risk.premium:+.1%} difference plus a "
                       f"{risk.buffer:.0%} buffer because confidence is {est.confidence.lower()}.")
        st.altair_chart(range_chart(est, d["price"], colors()), width="stretch")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Estimated value", aed_short(est.value_median))
        c1.caption(f"Likely {aed_short(est.value_p25)} to {aed_short(est.value_p75)}")
        c2.metric("Short if valued low (P25)", aed_short(low["shortfall"]))
        c2.caption(f"Buyer has {aed(d['cash_available'])}")
        c3.metric("Extra cash at median", aed_short(median["extra_cash_from_gap"]))
        c3.caption("Compared with a valuation at the price")
        c4.metric("Confidence", est.confidence)
        c4.caption(comps_source(est, d))


def comps_source(est, d: dict) -> str:
    spread = f"±{est.spread / 2:.0%}"
    if est.basis == "project":
        return f"{est.n_comps:,} sales in {est.comps['project'].iloc[0]} · {spread}"
    if d["project"]:
        return f"{est.n_comps:,} sales across the area (too few in {d['project']}) · {spread}"
    return f"{est.n_comps:,} sales across the area · {spread}"


def range_chart(est, price: float, c: dict) -> alt.Chart:
    """A strip showing where the agreed price sits against the likely valuation range.

    Blue band = P25 to P75, blue tick = median, orange line = the agreed price.
    Labels that would overlap are merged or dropped.
    """
    lo, mid, hi = est.value_p25, est.value_median, est.value_p75
    left, right = min(lo, price), max(hi, price)
    pad = (right - left) * 0.12
    start, end = left - pad, right + pad
    scale = alt.Scale(domain=[start, end])

    def at(value):  # position across the strip, 0 to 1
        return (value - start) / (end - start)

    band =alt.Chart(pd.DataFrame({"lo": [lo], "hi": [hi]})).mark_rect(
        color=c["comps"], opacity=0.2, cornerRadius=4
    ).encode(
        x=alt.X("lo:Q", scale=scale, axis=None), x2="hi:Q", y=alt.value(34), y2=alt.value(54),
        tooltip=[alt.Tooltip("lo:Q", title="Low valuation, P25 (AED)", format=",.0f"),
                 alt.Tooltip("hi:Q", title="High valuation, P75 (AED)", format=",.0f")],
    )
    median_tick = alt.Chart(pd.DataFrame({"v": [mid]})).mark_rule(color=c["comps"], strokeWidth=2).encode(
        x=alt.X("v:Q", scale=scale, axis=None), y=alt.value(30), y2=alt.value(58),
        tooltip=[alt.Tooltip("v:Q", title="Median estimate (AED)", format=",.0f")],
    )
    price_line = alt.Chart(pd.DataFrame({"v": [price]})).mark_rule(color=c["deal"], strokeWidth=3).encode(
        x=alt.X("v:Q", scale=scale, axis=None), y=alt.value(22), y2=alt.value(64),
        tooltip=[alt.Tooltip("v:Q", title="Agreed price (AED)", format=",.0f")],
    )

    def label(value, text, align, y, color, weight="normal"):
        return alt.Chart(pd.DataFrame({"v": [value], "t": [text]})).mark_text(
            align=align, baseline="bottom" if y < 34 else "top", color=color, fontWeight=weight, fontSize=12,
        ).encode(x=alt.X("v:Q", scale=scale, axis=None), y=alt.value(y), text="t:N")

    price_align = "left" if at(price) < 0.2 else "right" if at(price) > 0.8 else "center"
    labels = [label(price, f"Agreed price {aed_short(price)}", price_align, 18, c["ink"], "bold")]
    if at(hi) - at(lo) < 0.4:  # narrow band: one label for the whole range
        labels.append(label(mid, f"Likely valuation {aed_short(lo)} to {aed_short(hi)}", "center", 66, c["muted"]))
    else:
        labels.append(label(lo, f"P25 {aed_short(lo)}", "left", 66, c["muted"]))
        labels.append(label(hi, f"P75 {aed_short(hi)}", "right", 66, c["muted"]))
        if min(at(mid) - at(lo), at(hi) - at(mid)) > 0.15:  # room for the median label in between
            labels.append(label(mid, f"Median {aed_short(mid)}", "center", 66, c["muted"]))

    return (alt.layer(band, median_tick, price_line, *labels)
            .properties(height=86)
            .configure_view(stroke=None))


def note_card(note: str, title: str = "What this means") -> None:
    with st.container(border=True):
        st.markdown(f"**{title}**")
        st.markdown(note)


def cash_table(scenarios: pd.DataFrame, settings: dict) -> None:
    table = scenarios.set_index("name")[list(SCENARIO_ROWS.values())].T
    table.index = list(SCENARIO_ROWS)
    table = table.rename(columns=SCENARIO_NAMES)
    bad = colors()["bad"]
    styled = (table.style.format("AED {:,.0f}")
              .map(lambda v: f"color: {bad}; font-weight: 600" if v > 0 else "",
                   subset=pd.IndexSlice[["Short by"], :])
              .map(lambda v: "font-weight: 600", subset=pd.IndexSlice[["Cash needed at completion"], :]))
    st.table(styled)
    st.caption(
        f"Loan = {settings['ltv']:.0%} of the lower of price and valuation. Sooner pays closing costs up to "
        f"{config.SOONER_MAX_SHARE:.0%} of the {settings['value_basis']} (max {aed(config.SOONER_CAP_AED)}), "
        f"repaid over {config.SOONER_TERM_MONTHS} months with a flat yearly fee of {settings['fee_rate']:.1%}."
    )


def comparable_sales(est, d: dict) -> None:
    deal_psf = per_sqft(d["price"] / d["size_sqm"])
    st.altair_chart(price_chart(est, deal_psf, colors()), width="stretch")
    st.caption("Each dot is a sale. Fainter dots are older and count less. "
               "The shaded band is the likely range (P25 to P75).")
    table = est.comps.assign(
        project=est.comps["project"].fillna("–"),
        size_sqft=(est.comps["size_sqm"] * config.SQFT_PER_SQM).round(0),
        price_per_sqft=(est.comps["price_per_sqm"] / config.SQFT_PER_SQM).round(0),
    )[["date", "project", "bedrooms", "size_sqft", "price_aed", "price_per_sqft", "weight"]]
    st.dataframe(table, hide_index=True, width="stretch", height=320, column_config={
        "date": st.column_config.DateColumn("Date", format="D MMM YYYY"),
        "project": "Building",
        "bedrooms": "Beds",
        "size_sqft": st.column_config.NumberColumn("Size (sqft)", format="localized"),
        "price_aed": st.column_config.NumberColumn("Price (AED)", format="localized"),
        "price_per_sqft": st.column_config.NumberColumn("AED per sqft", format="localized"),
        "weight": st.column_config.ProgressColumn("Weight", min_value=0, max_value=1, format="percent"),
    })


def price_chart(est, deal_psf: float, c: dict) -> alt.Chart:
    """Comparable sales over time, with the likely range, the median and this deal.

    The two reference lines are named in a legend above the chart rather than
    labelled on the plot, because in busy areas the dots would bury the labels.
    """
    comps = est.comps.assign(
        price_per_sqft=lambda x: (x["price_per_sqm"] / config.SQFT_PER_SQM).round(0),
        size_sqft=lambda x: (x["size_sqm"] * config.SQFT_PER_SQM).round(0),
    )
    p25, median, p75 = (per_sqft(x) for x in (est.ppsqm_p25, est.ppsqm_median, est.ppsqm_p75))

    band = alt.Chart(pd.DataFrame({"p25": [p25], "p75": [p75]})).mark_rect(
        color=c["comps"], opacity=0.10
    ).encode(y="p25:Q", y2="p75:Q")

    dots = alt.Chart(comps).mark_circle(
        size=70, color=c["comps"], stroke=c["surface"], strokeWidth=2
    ).encode(
        x=alt.X("date:T", title="Sale date", axis=alt.Axis(format="%b", tickCount="month")),
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
                        scale=alt.Scale(domain=refs["label"].tolist(), range=[c["comps"], c["deal"]]),
                        legend=alt.Legend(orient="top", symbolType="stroke", labelColor=c["ink"],
                                          labelLimit=400)),
    )
    return alt.layer(band, dots, rules).properties(height=360)


def closing_cost_lines(d: dict, settings: dict) -> None:
    costs = closing_costs(d["price"], loan_amount(d["price"], d["price"], settings["ltv"]))
    lines = pd.Series(costs, name="Amount").to_frame()
    lines.loc["Total"] = sum(costs.values())
    st.table(lines.style.format("AED {:,.0f}")
             .map(lambda v: "font-weight: 600", subset=pd.IndexSlice[["Total"], :]))
    st.caption("If the bank values the home at the agreed price. Fee lines from Sooner's site; VAT applies "
               "to every line except DLD fees and mortgage registration.")


def no_estimate(sales: pd.DataFrame, d: dict, home: tuple) -> None:
    found, _ = find_comps(sales, *home)
    with st.container(border=True):
        st.badge("No estimate", color="gray", icon=":material/search_off:")
        st.markdown("### Not enough comparable sales")
        st.markdown(
            f"Found {len(found)} {describe_home(d['property_type'], d['bedrooms'])} in {d['area']} within "
            f"{config.SIZE_TOLERANCE:.0%} of {d['size_sqft']:,.0f} sqft, and at least {config.MIN_COMPS} are "
            "needed. Try a size closer to the typical one shown in the sidebar, or a nearby area."
        )


# ---------------------------------------------------------------------------
# Pipeline (batch) mode
# ---------------------------------------------------------------------------

# Decision columns first, so they're visible without scrolling sideways.
REPORT_VIEW = {
    "deal_id": st.column_config.TextColumn("Deal", pinned=True),
    "risk": "Risk",
    "area": "Area",
    "price": "Price (AED)",
    "price_vs_estimate": "vs estimate",
    "short_median": "Short at median (AED)",
    "short_p25": "Short at P25 (AED)",
    "confidence": "Confidence",
    "notes": st.column_config.TextColumn("Notes", width="large"),
    "estimate": "Estimate (AED)",
    "building": "Building",
    "property_type": "Type",
    "bedrooms": "Beds",
}

REPORT_FORMATS = {
    "bedrooms": "{:.0f}",
    "price": "{:,.0f}",
    "estimate": "{:,.0f}",
    "price_vs_estimate": "{:+.1%}",
    "short_median": "{:,.0f}",
    "short_p25": "{:,.0f}",
}


def show_batch(sales: pd.DataFrame, settings: dict) -> None:
    st.header("Pipeline check")
    st.caption("Every deal in a CSV, checked at once and sorted riskiest first.")

    with st.container(border=True):
        left, right = st.columns([3, 1], vertical_alignment="center")
        upload = left.file_uploader("Pipeline CSV", type="csv", label_visibility="collapsed")
        right.download_button("Example CSV", config.EXAMPLE_PIPELINE_PATH.read_bytes(),
                              file_name="pipeline_example.csv", mime="text/csv",
                              icon=":material/download:", width="stretch")
        st.caption(f"One deal per row. Columns: {', '.join(REQUIRED_COLUMNS)}, and optionally building. "
                   "Sizes in sqft; bedrooms can be 'studio'; shorthands like JVC, JLT and Marina work.")
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
    short = assessed[assessed["short_median"] > 0]
    short_p25 = assessed[assessed["short_p25"] > 0]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Deals checked", len(report), border=True, icon=":material/fact_check:")
    c1.caption(f"{len(assessed)} assessed, {len(report) - len(assessed)} couldn't be")
    c2.metric("High risk", int((report["risk"] == "High").sum()), border=True, icon=":material/error:")
    c2.caption(f"Plus {int((report['risk'] == 'Medium').sum())} at Medium risk")
    c3.metric("Short at median", len(short), border=True, icon=":material/account_balance_wallet:")
    c3.caption(f"Buyers short if valued at the median: {aed(short['short_median'].sum())} in total")
    c4.metric("Short at P25", len(short_p25), border=True, icon=":material/trending_down:")
    c4.caption(f"Buyers short if valued low: {aed(short_p25['short_p25'].sum())} in total")

    # Report, riskiest first
    st.subheader("Deals, riskiest first")
    view = report[list(REPORT_VIEW)].fillna({"confidence": "–"})
    styled = (view.style
              .format(REPORT_FORMATS, na_rep="–")
              .map(lambda level: RISK_TINT.get(level, ""), subset=["risk"]))
    rows_shown = min(len(view), 20)  # show every row of a small pipeline without scrolling
    st.dataframe(styled, hide_index=True, width="stretch", height=35 * (rows_shown + 1) + 3,
                 column_config=REPORT_VIEW)
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
    color, icon = RISK_STYLE[row["risk"]]
    with st.container(border=True):
        st.badge(f"{row['risk']} gap risk", color=color, icon=icon)
        st.markdown(f"### {row['deal_id']}: {row['area']}, {aed(row['price'])}")
        st.markdown(row["advisor_note"])


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

def data_footer(sales: pd.DataFrame) -> None:
    source = ("All areas in the DLD data." if config.PROCESSED_PATH.exists()
              else f"Sample data: the {config.SAMPLE_AREAS} busiest areas for apartments and for villas.")
    st.divider()
    st.caption(
        f"Based on {len(sales):,} DLD sales of ready freehold homes, "
        f"{sales['date'].min():%d %b %Y} to {sales['date'].max():%d %b %Y}. {source} "
        "This is an estimate from past sales, not a bank valuation."
    )


def main() -> None:
    sales = get_sales()
    mode = sidebar_header()
    if mode == "One deal":
        deal = deal_inputs(sales)
        settings = settings_inputs()
        show_deal(sales, deal, settings)
    else:
        settings = settings_inputs()
        show_batch(sales, settings)
    data_footer(sales)


main()
