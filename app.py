"""Valuation Gap Radar: the Streamlit app.

Run it from the project root:

    streamlit run app.py

Three views, chosen at the top of the sidebar:

- Deal: check one deal before the Form F is signed
- Pipeline: check every deal in a CSV export
- Method: the problem, how the estimate works, assumptions, accuracy, limits

All the maths lives in the radar/ package; this file only collects inputs and
shows results. Sizes and prices are shown per sqft, as Dubai listings quote
them; the engine works in sqm, so the conversion happens here at the edge.

Colours and fonts are set in .streamlit/config.toml, styled after
joinsooner.com. One colour rule runs through the app: lime marks Sooner's
money (and the brand mark), blue the market and the bank, orange the agreed
price, grey the buyer's cash and red a shortfall.
"""

import importlib

import altair as alt
import pandas as pd
import streamlit as st

import radar.advisor
import radar.batch
import radar.cash
import radar.comps
import radar.config
import radar.etl

# Streamlit Cloud re-runs the new app.py after a git push but keeps the old
# radar/ modules in memory, so a push that changed both crashed the live app.
# Reloading them here, in the order they depend on each other, keeps the code
# in step. It takes a few milliseconds per run.
for _module in (radar.config, radar.etl, radar.comps, radar.cash, radar.advisor, radar.batch):
    importlib.reload(_module)

from radar import config
from radar.advisor import advisor_note, aed, describe_home, per_sqft
from radar.batch import REQUIRED_COLUMNS, assess_deals, pipeline_summary, read_deals
from radar.cash import check_eligibility, closing_costs, loan_amount, scenario_table
from radar.comps import estimate_value, find_comps, gap_risk
from radar.etl import load_sales

st.set_page_config(page_title="Valuation Gap Radar", page_icon=":material/radar:", layout="wide")

# Two small rules on top of the theme: keep lines readable on wide screens,
# and line up the figures in tables.
PAGE_CSS = """
<style>
[data-testid="stMainBlockContainer"] { max-width: 1180px; margin: 0 auto; }
[data-testid="stTable"] { font-variant-numeric: tabular-nums; }
</style>
"""

# Chart colours, checked for colour-blind safety against the light and dark
# backgrounds. Text uses ink colours, never the data colours.
COLORS = {
    "light": {"comps": "#2a78d6", "deal": "#eb6834", "surface": "#ffffff", "band": 0.2,
              "ink": "#0e0d0d", "muted": "#6e6e6e", "bad": "#a82828",
              "buyer": "#4a4646", "buyer_ink": "#ffffff"},
    "dark": {"comps": "#3987e5", "deal": "#d95926", "surface": "#0e0d0d", "band": 0.4,
             "ink": "#f4f4f4", "muted": "#9f9e9e", "bad": "#ff8a8a",
             "buyer": "#cfcfcf", "buyer_ink": "#0e0d0d"},
}
# Sooner's lime. Text on it is always near-black, as on joinsooner.com, so it
# reads the same in light and dark mode.
LIME = "background-color: #e9fe0f; color: #0e0d0d; font-weight: 600"

# Each risk level has a colour and an icon, so colour is never the only cue.
RISK_STYLE = {
    "Low": ("green", ":material/check_circle:"),
    "Medium": ("orange", ":material/warning:"),
    "High": ("red", ":material/error:"),
}
RISK_HEADLINE = {
    "High": "Likely to be valued below the agreed price",
    "Medium": "Could be valued slightly below the agreed price",
    "Low": "Agreed price is in line with recent sales",
}
RISK_TINT = {  # see-through, so it works on light and dark backgrounds
    "High": "background-color: rgba(208, 59, 59, 0.16)",
    "Medium": "background-color: rgba(232, 137, 12, 0.18)",
    "Low": "background-color: rgba(12, 163, 12, 0.13)",
}

SCENARIO_NAMES = {"P25": "Low valuation", "Median": "Typical valuation", "P75": "High valuation"}

SCENARIO_ROWS = {
    "Bank valuation": "valuation",
    "Bank loan": "loan",
    "Down payment": "down_payment",
    "Closing fees": "closing_costs",
    "Paid by Sooner": "sooner_support",
    "Cash the buyer needs": "cash_needed",
    "Extra cash from the valuation gap": "extra_cash_from_gap",
    "Buyer short by": "shortfall",
    "Monthly repayment to Sooner": "monthly_repayment",
}

FEE_BASIS = {
    "Dubai Land Department": f"{config.DLD_RATE:.0%} of the price + AED {config.DLD_ADMIN_AED:,}",
    "DLD title deed": f"AED {config.DLD_TITLE_DEED_AED:,}",
    "Agency commission": f"{config.AGENCY_RATE:.0%} of the price + VAT",
    "Bank arrangement fee": f"{config.BANK_ARRANGEMENT_RATE:.0%} of the loan + VAT",
    "Mortgage registration": f"{config.MORTGAGE_REGISTRATION_RATE:.2%} of the loan "
                             f"+ AED {config.MORTGAGE_REGISTRATION_ADMIN_AED:,}",
    "Valuation": f"AED {config.VALUATION_AED:,} + VAT",
    "Trustee": f"AED {config.TRUSTEE_AED:,} + VAT",
    "NOC": f"AED {config.NOC_AED:,} + VAT (developer's no-objection certificate)",
    "Conveyancing": f"AED {config.CONVEYANCING_AED:,} + VAT",
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


def aed_round(amount: float) -> str:
    """AED 941,000: rounded to the nearest thousand for sentences."""
    return aed(round(amount, -3))


def lime(text: str) -> str:
    """Wrap fixed text in Sooner's lime. Only ever pass our own text, never user input."""
    return f'<span style="{LIME}; padding: 0 0.15em; border-radius: 3px">{text}</span>'


def home_label(property_type: str, bedrooms: int) -> str:
    """'Studio apartment', '2-bed apartment', '3-bed villa'."""
    kind = property_type.lower()
    return f"Studio {kind}" if bedrooms == 0 else f"{bedrooms}-bed {kind}"


def text_card(title: str, body: str) -> None:
    with st.container(border=True, height="stretch"):
        st.markdown(f"**{title}**")
        st.markdown(body)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

VIEWS = {"Deal": None, "Pipeline": "pipeline", "Method": "method"}  # view -> ?mode= value


def sidebar_header() -> str:
    """Brand, one-line purpose and the view switch. Returns the chosen view."""
    sb = st.sidebar
    sb.markdown(f"### Valuation Gap {lime('Radar')}", unsafe_allow_html=True)
    sb.caption("Down-valuation check for Sooner deals")
    # ?mode=pipeline or ?mode=method in the URL opens that view, e.g. for a shared link;
    # no mode opens the Deal view. Only the first run of a session reads it.
    if "view" not in st.session_state:
        requested = st.query_params.get("mode")
        st.session_state.view = next((view for view, mode in VIEWS.items() if mode == requested), "Deal")
    view = sb.segmented_control("View", list(VIEWS), key="view", required=True,
                                label_visibility="collapsed", width="stretch")
    # Keep the URL in step with the view, so a refresh stays on it and the plain link opens Deal.
    mode = VIEWS[view]
    if st.query_params.get("mode") != mode:
        if mode is None:
            del st.query_params["mode"]
        else:
            st.query_params["mode"] = mode
    return view


def deal_inputs(sales: pd.DataFrame) -> dict:
    """The property and the deal. Dropdowns only offer what has sales, with counts."""
    sb = st.sidebar
    sb.markdown("**Property**")
    area_counts = sales["area"].value_counts()
    areas = sorted(area_counts.index)
    # No sales counts here: long community names plus a count get cut off in the sidebar.
    area = sb.selectbox("Area", areas, index=areas.index(area_counts.index[0]),
                        help="Community name as registered with the Dubai Land Department.")

    in_area = sales[sales["area"] == area]
    types = sorted(in_area["property_type"].unique())
    property_type = sb.segmented_control("Type", types, default=types[0], required=True)

    of_type = in_area[in_area["property_type"] == property_type]
    bed_counts = of_type["bedrooms"].value_counts().sort_index()
    bedrooms = sb.selectbox("Bedrooms", bed_counts.index, index=int(bed_counts.argmax()),
                            format_func=lambda b: f"{'Studio' if b == 0 else b} ({bed_counts[b]:,} sales)")

    homes = of_type[of_type["bedrooms"] == bedrooms]
    project_counts = homes["project"].value_counts()
    project = sb.selectbox(
        "Building", [None, *project_counts.index],
        format_func=lambda p: "Any building in the area" if p is None else f"{p} ({project_counts[p]} sales)",
        help="Optional. Sales in the same building are the closest comparison and sharpen the estimate.",
    )
    size_sqft = sb.number_input("Size (sqft)", min_value=150, max_value=30_000, value=750, step=10)
    typical = homes["size_sqm"].median() * config.SQFT_PER_SQM
    sb.caption(f"Typical here: {typical:,.0f} sqft")

    sb.markdown("**Deal**")
    price = sb.number_input("Agreed price (AED)", min_value=100_000, value=1_000_000, step=10_000,
                            help="The price on the Form F.")
    sb.caption(aed(price))  # number inputs can't show thousands separators, so repeat it here
    cash = sb.number_input("Buyer's cash (AED)", min_value=0, value=250_000, step=5_000,
                           help="All the cash the buyer can bring at completion, including the down payment. "
                                "Sooner pays the closing fees separately.")
    sb.caption(aed(cash))

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
    """The assumptions that apply to every deal, in the Deal and Pipeline views."""
    with st.sidebar.expander("Assumptions"):
        ltv = st.slider("Bank loan (% of value)", 50, 85, round(config.DEFAULT_LTV * 100), 5,
                        help="Loan-to-value. 80% is the cap for an expat's first home under AED 5M; "
                             "use less for a second home or a home over AED 5M.")
        # round() because 0.07 * 100 is 7.000000000000001 in floating point
        fee = st.slider("Sooner yearly fee (%)", round(config.SOONER_FEE_MIN * 100, 1),
                        round(config.SOONER_FEE_MAX * 100, 1), round(config.SOONER_FEE_DEFAULT * 100, 1), 0.5,
                        help="Flat fee per year. Only changes the monthly repayment.")
        value_basis = st.radio("Sooner's 10% limit is based on", ["price", "valuation"],
                               format_func=str.capitalize, help="To be confirmed with Sooner.")
    return {"ltv": ltv / 100, "fee_rate": fee / 100, "value_basis": value_basis}


# ---------------------------------------------------------------------------
# Deal view
# ---------------------------------------------------------------------------

def show_deal(sales: pd.DataFrame, d: dict, settings: dict) -> None:
    st.header(f"{home_label(d['property_type'], d['bedrooms'])}, {d['area']}", anchor=False)
    st.caption(" · ".join([f"{d['size_sqft']:,.0f} sqft", d["project"] or "Any building",
                           f"Agreed price {aed(d['price'])}", f"Buyer's cash {aed(d['cash_available'])}"]))

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
                        estimate=est, risk=risk, scenarios=scenarios, include_actions=False)

    verdict_card(d, est, risk, scenarios)
    who_pays(d, est, settings)

    left, right = st.columns([3, 2], gap="medium")
    with left:
        text_card("Advisor note", note)
    with right:
        text_card("Next steps", "\n".join(f"- {step}" for step in next_steps(est, risk, scenarios)))

    cash_tab, comps_tab, fees_tab = st.tabs(["Cash breakdown", "Comparable sales", "Closing fees"])
    with cash_tab:
        cash_table(scenarios, settings)
    with comps_tab:
        comparable_sales(est, d)
    with fees_tab:
        closing_fee_lines(d, settings)


def verdict_card(d: dict, est, risk, scenarios: pd.DataFrame) -> None:
    """The answer first: risk level, where the price sits, and the cash at stake."""
    color, icon = RISK_STYLE[risk.level]
    by_name = scenarios.set_index("name")
    low, typical = by_name.loc["P25"], by_name.loc["Median"]

    headline = RISK_HEADLINE[risk.level]
    if risk.level == "Low" and risk.premium <= 0:
        headline = "Agreed price is at or below recent sales"
    if abs(risk.premium) < 0.005:
        comparison = f"The agreed price matches the estimated valuation of {aed_round(est.value_median)}."
    else:
        direction = "above" if risk.premium > 0 else "below"
        comparison = (f"The agreed price is {abs(risk.premium):.0%} {direction} the estimated valuation "
                      f"of {aed_round(est.value_median)}.")
    why = (f"Risk score {risk.score:+.1%}: the price is {risk.premium:+.1%} against the estimate"
           + (f", plus {risk.buffer * 100:.0f} points because confidence is {est.confidence.lower()}"
              if risk.buffer else "")
           + f". Medium from {config.MEDIUM_RISK_FROM:.0%}, High from {config.HIGH_RISK_FROM:.0%}.")

    with st.container(border=True):
        st.badge(f"{risk.level} risk", color=color, icon=icon, help=why)
        st.subheader(headline, anchor=False)
        st.markdown(comparison)
        st.altair_chart(range_chart(est, d["price"], colors()), width="stretch")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Estimated valuation", aed_short(est.value_median),
                  help="Typical price per sqft of similar recent sales, times this home's size. "
                       "Recent sales count more.")
        c1.caption(f"Range {aed_short(est.value_p25)} to {aed_short(est.value_p75)}")
        c2.metric("Buyer short by", aed_short(low["shortfall"]),
                  help="At the low valuation: the cash needed at completion minus the buyer's cash.")
        c2.caption("at the low valuation" if low["shortfall"] > 0 else "Their cash covers the low valuation")
        c3.metric("Extra cash needed", aed_short(typical["extra_cash_from_gap"]),
                  help="How much more cash the buyer needs than if the bank valued the home at the agreed price.")
        c3.caption("at the typical valuation")
        c4.metric("Confidence", est.confidence,
                  help="High: many similar sales with closely matching prices. Low: few sales, or prices "
                       "that vary widely. Choosing the building usually raises it.")
        c4.caption(comps_source(est, d))


def comps_source(est, d: dict) -> str:
    spread = f"±{est.spread / 2:.0%}"
    if est.basis == "project":
        return f"{est.n_comps:,} sales in {est.comps['project'].iloc[0]}, {spread}"
    if d["project"]:
        return f"{est.n_comps:,} sales in the area (too few in {d['project']}), {spread}"
    return f"{est.n_comps:,} sales in the area, {spread}"


def range_chart(est, price: float, c: dict) -> alt.Chart:
    """A strip showing where the agreed price sits against the likely valuation range.

    Blue band = low to high valuation, blue tick = the estimate, orange line =
    the agreed price. The price is labelled above the band and the estimate
    below it, each centred on its own line, so those two can never overlap.
    Low and High sit at the band's ends on the row below, but only when the
    chart is wide enough to fit them beside the estimate label; on a phone the
    range is in the caption under the strip instead.
    """
    lo, mid, hi = est.value_p25, est.value_median, est.value_p75
    left, right = min(lo, price), max(hi, price)
    pad = (right - left) * 0.12
    start, end = left - pad, right + pad
    scale = alt.Scale(domain=[start, end])

    def at(value):  # position across the strip, 0 to 1
        return (value - start) / (end - start)

    def align_at(value):  # a label near an edge grows inwards, so it stays inside the chart
        return "left" if at(value) < 0.25 else "right" if at(value) > 0.75 else "center"

    above, band_top, band_bottom = 16, 26, 46  # pixels from the top
    below = band_bottom + 8
    band = alt.Chart(pd.DataFrame({"lo": [lo], "hi": [hi]})).mark_rect(
        color=c["comps"], opacity=c["band"], cornerRadius=4
    ).encode(
        x=alt.X("lo:Q", scale=scale, axis=None), x2="hi:Q", y=alt.value(band_top), y2=alt.value(band_bottom),
        tooltip=[alt.Tooltip("lo:Q", title="Low valuation (AED)", format=",.0f"),
                 alt.Tooltip("hi:Q", title="High valuation (AED)", format=",.0f")],
    )
    estimate_tick = alt.Chart(pd.DataFrame({"v": [mid]})).mark_rule(color=c["comps"], strokeWidth=2).encode(
        x=alt.X("v:Q", scale=scale, axis=None), y=alt.value(band_top - 3), y2=alt.value(band_bottom + 4),
        tooltip=[alt.Tooltip("v:Q", title="Estimated valuation (AED)", format=",.0f")],
    )
    # The price line stops short of the labels under the band, so it never crosses one.
    price_line = alt.Chart(pd.DataFrame({"v": [price]})).mark_rule(color=c["deal"], strokeWidth=3).encode(
        x=alt.X("v:Q", scale=scale, axis=None), y=alt.value(above + 4), y2=alt.value(band_bottom + 3),
        tooltip=[alt.Tooltip("v:Q", title="Agreed price (AED)", format=",.0f")],
    )

    def label(value, text, align, y, color, weight="normal", opacity=1):
        return alt.Chart(pd.DataFrame({"v": [value], "t": [text]})).mark_text(
            align=align, baseline="bottom" if y < band_top else "top", color=color, fontWeight=weight, fontSize=12,
            opacity=opacity,
        ).encode(x=alt.X("v:Q", scale=scale, axis=None), y=alt.value(y), text="t:N")

    def text_px(text):  # rough width of a 12px label; Manrope averages about 6.2px a character
        return len(text) * 6.5

    estimate_text, low_text, high_text = (f"Estimate {aed_short(mid)}", f"Low {aed_short(lo)}",
                                          f"High {aed_short(hi)}")
    estimate_align = align_at(mid)
    # How far the estimate label reaches left and right of its tick, in pixels.
    reach_left = {"left": 0, "center": text_px(estimate_text) / 2, "right": text_px(estimate_text)}[estimate_align]
    reach_right = text_px(estimate_text) - reach_left
    # Vega knows the chart's real width ("width" here), so Low and High appear only
    # when both fit beside the estimate label with a 12px gap.
    ends_fit = alt.ExprRef(
        f"({at(mid) - at(lo):.4f} * width >= {reach_left + text_px(low_text) + 12:.0f}) && "
        f"({at(hi) - at(mid):.4f} * width >= {reach_right + text_px(high_text) + 12:.0f}) ? 1 : 0"
    )
    labels = [
        label(price, f"Agreed price {aed_short(price)}", align_at(price), above, c["ink"], "bold"),
        label(mid, estimate_text, estimate_align, below, c["ink"]),
        label(lo, low_text, "left", below, c["muted"], opacity=ends_fit),
        label(hi, high_text, "right", below, c["muted"], opacity=ends_fit),
    ]

    return (alt.layer(band, estimate_tick, price_line, *labels)
            .properties(height=below + 16)
            .configure_view(stroke=None))


def who_pays(d: dict, est, settings: dict) -> None:
    """Who pays for the home if the bank values it at the price, and if it values low.

    This is the heart of the problem: Sooner covers the fees, but a low
    valuation grows the buyer's share of the price, which Sooner can't cover.
    """
    split = scenario_table(
        d["price"],
        {"Valued at the price": d["price"], f"Valued low ({aed_short(est.value_p25)})": est.value_p25},
        d["cash_available"], **settings,
    )
    at_price, low = split.iloc[0], split.iloc[1]
    extra = low["cash_needed"] - at_price["cash_needed"]

    st.subheader("Who pays", anchor=False)
    st.altair_chart(who_pays_chart(split, d["cash_available"], colors()), width="stretch")
    text = (f"The bank lends {settings['ltv']:.0%} of the lower of the price and its valuation, the buyer pays "
            "the rest of the price, and Sooner pays the closing fees.")
    if extra > 0:
        text += f" At the low valuation the loan falls to {aed(low['loan'])}, so the buyer needs {aed(extra)} more."
        if low["shortfall"] > 0:
            deposit = config.FORM_F_DEPOSIT_SHARE * d["price"]
            text += (f" That leaves them {aed(low['shortfall'])} short. If they can't raise it, the sale can fall "
                     f"through and their Form F deposit of about {aed_round(deposit)} is at risk.")
    else:
        text += " Even the low valuation is at or above the price, so the buyer's share doesn't change."
    st.markdown(text)


def who_pays_chart(split: pd.DataFrame, cash: float, c: dict) -> alt.Chart:
    """One bar per scenario: the bank's loan, the buyer's cash, any shortfall, and Sooner's fees.

    Scenario names sit above each bar rather than beside it, so the bars use the
    full width and still read on a phone.
    """
    parts = ["Bank", "Buyer", "Shortfall", "Sooner"]
    fills = [c["comps"], c["buyer"], "#d03b3b", "#e9fe0f"]
    inks = ["#ffffff", c["buyer_ink"], "#ffffff", "#0e0d0d"]  # label colour on each fill
    rows = []
    for _, s in split.iterrows():
        amounts = [s["loan"], min(s["cash_needed"], cash), s["shortfall"], s["sooner_support"]]
        start = 0.0
        for part, amount, ink in zip(parts, amounts, inks):
            rows.append({"scenario": s["name"], "part": part, "start": start, "end": start + amount,
                         "mid": start + amount / 2, "amount": amount, "label": aed_short(amount), "ink": ink})
            start += amount
    data = pd.DataFrame(rows)
    data = data[data["amount"] > 0]
    total = data["end"].max()
    x_scale = alt.Scale(domain=[0, total])
    y = alt.Y("scenario:N", sort=split["name"].tolist(), axis=None)

    bars = alt.Chart(data).mark_bar(size=22, cornerRadius=3, stroke=c["surface"], strokeWidth=2).encode(
        y=y, x=alt.X("start:Q", scale=x_scale, axis=None), x2="end:Q",
        color=alt.Color("part:N", scale=alt.Scale(domain=parts, range=fills),
                        legend=alt.Legend(orient="top", title=None, labelColor=c["ink"], symbolType="square")),
        tooltip=[alt.Tooltip("scenario:N", title="Scenario"), alt.Tooltip("part:N", title="Paid by"),
                 alt.Tooltip("amount:Q", title="AED", format=",.0f")],
    )
    names = alt.Chart(split[["name"]].rename(columns={"name": "scenario"})).mark_text(
        align="left", baseline="bottom", dy=-15, fontSize=12, color=c["ink"],
    ).encode(y=y, x=alt.value(0), text="scenario:N")
    # The shortfall matters most, so it is always labelled: above the bar, ending where its
    # segment ends (always near the right, so clear of the scenario name).
    short = data[data["part"] == "Shortfall"].assign(text=lambda x: "Short " + x["label"])
    short_label = alt.Chart(short).mark_text(
        align="right", baseline="bottom", dy=-15, fontSize=12, fontWeight=600, color=c["bad"],
    ).encode(y=y, x=alt.X("end:Q", scale=x_scale, axis=None), text="text:N")
    # Write other amounts inside their segment only when it's wide enough to hold them, even on a phone.
    inside = data[(data["amount"] / total > 0.14) & (data["part"] != "Shortfall")]
    amounts = alt.Chart(inside).mark_text(fontSize=11, fontWeight=600).encode(
        y=y, x=alt.X("mid:Q", scale=x_scale, axis=None), text="label:N", color=alt.Color("ink:N", scale=None),
    )
    # A fixed height per row (not for the whole chart) keeps the bars and their names apart.
    return (alt.layer(bars, names, short_label, amounts)
            .properties(height=alt.Step(62))
            .configure_view(stroke=None))


def next_steps(est, risk, scenarios: pd.DataFrame) -> list[str]:
    """A short checklist for the advisor, matching the risk level."""
    by_name = scenarios.set_index("name")
    low, typical = by_name.loc["P25"], by_name.loc["Median"]
    steps = []
    if risk.level == "High":
        steps += [
            "Get a bank pre-valuation before the Form F is signed.",
            f"Negotiate the price towards {aed_round(est.value_median)}.",
            "Add a Form F clause that returns the deposit if the valuation comes in low.",
        ]
    elif risk.level == "Medium":
        if typical["extra_cash_from_gap"] > 0:
            steps.append(f"Confirm the buyer can cover {aed(typical['extra_cash_from_gap'])} extra.")
        steps.append("Consider a bank pre-valuation before the Form F is signed.")
    else:
        steps.append("No action needed on the valuation.")
    if low["shortfall"] > 0:
        steps.append(f"Check the buyer could raise {aed(low['shortfall'])} if the bank values low.")
    if est.confidence == "Low" and est.basis == "area":
        steps.append("Choose the building to sharpen the estimate.")
    return steps


def cash_table(scenarios: pd.DataFrame, settings: dict) -> None:
    table = scenarios.set_index("name")[list(SCENARIO_ROWS.values())].T
    table.index = list(SCENARIO_ROWS)
    table = table.rename(columns=SCENARIO_NAMES)
    bad = colors()["bad"]
    styled = (table.style.format("{:,.0f}")
              .map(lambda v: LIME, subset=pd.IndexSlice[["Paid by Sooner"], :])
              .map(lambda v: f"color: {bad}; font-weight: 600" if v > 0 else "",
                   subset=pd.IndexSlice[["Buyer short by"], :])
              .map(lambda v: "font-weight: 600", subset=pd.IndexSlice[["Cash the buyer needs"], :]))
    st.table(styled)
    st.caption(f"Amounts in AED. Bank loan: {settings['ltv']:.0%} of the lower of price and valuation. "
               f"Sooner covers closing fees "
               f"up to {config.SOONER_MAX_SHARE:.0%} of the {settings['value_basis']} (max "
               f"{aed(config.SOONER_CAP_AED)}), repaid over {config.SOONER_TERM_MONTHS} months at a flat "
               f"{settings['fee_rate']:.1%} a year.")


def comparable_sales(est, d: dict) -> None:
    st.caption("Sales of similar homes: same area, type and bedrooms, size within 20%. "
               "Faded dots are older and count less in the estimate.")
    deal_psf = per_sqft(d["price"] / d["size_sqm"])
    st.altair_chart(price_chart(est, deal_psf, colors()), width="stretch")
    table = est.comps.assign(
        project=est.comps["project"].fillna("–"),
        size_sqft=(est.comps["size_sqm"] * config.SQFT_PER_SQM).round(0),
        price_per_sqft=(est.comps["price_per_sqm"] / config.SQFT_PER_SQM).round(0),
    )[["date", "project", "bedrooms", "size_sqft", "price_aed", "price_per_sqft", "weight"]]
    st.dataframe(table, hide_index=True, width="stretch", height=320, column_config={
        "date": st.column_config.DateColumn("Sold on", format="D MMM YYYY"),
        "project": "Building",
        "bedrooms": "Beds",
        "size_sqft": st.column_config.NumberColumn("Size (sqft)", format="localized"),
        "price_aed": st.column_config.NumberColumn("Price (AED)", format="localized"),
        "price_per_sqft": st.column_config.NumberColumn("AED per sqft", format="localized"),
        "weight": st.column_config.ProgressColumn(
            "Weight", min_value=0, max_value=1, format="percent",
            help="How much the sale counts in the estimate. It halves every 4 months."),
    })


def price_chart(est, deal_psf: float, c: dict) -> alt.Chart:
    """Similar sales over time, with the likely range, the typical price and this deal.

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
            alt.Tooltip("date:T", title="Sold on", format="%d %b %Y"),
            alt.Tooltip("project:N", title="Building"),
            alt.Tooltip("size_sqft:Q", title="Size (sqft)", format=",.0f"),
            alt.Tooltip("price_aed:Q", title="Price (AED)", format=",.0f"),
            alt.Tooltip("price_per_sqft:Q", title="AED per sqft", format=",.0f"),
            alt.Tooltip("weight:Q", title="Weight", format=".0%"),
        ],
    )

    refs = pd.DataFrame({
        "value": [median, deal_psf],
        "label": [f"Typical sale: AED {median:,.0f}/sqft", f"This deal: AED {deal_psf:,.0f}/sqft"],
    })
    rules = alt.Chart(refs).mark_rule(strokeWidth=2).encode(
        y="value:Q",
        color=alt.Color("label:N", title=None,
                        scale=alt.Scale(domain=refs["label"].tolist(), range=[c["comps"], c["deal"]]),
                        legend=alt.Legend(orient="top", symbolType="stroke", labelColor=c["ink"],
                                          labelLimit=400)),
    )
    return alt.layer(band, dots, rules).properties(height=360)


def closing_fee_lines(d: dict, settings: dict) -> None:
    costs = closing_costs(d["price"], loan_amount(d["price"], d["price"], settings["ltv"]))
    lines = pd.DataFrame({"Basis": [FEE_BASIS.get(k, "") for k in costs],
                          "Amount (AED)": list(costs.values())}, index=list(costs))
    lines.loc["Total"] = ["", sum(costs.values())]
    st.table(lines.style.format({"Amount (AED)": "{:,.0f}"})
             .map(lambda v: "font-weight: 600", subset=pd.IndexSlice[["Total"], :]))
    st.caption("At the agreed price, with the same lines as Sooner's calculator. Amounts include 5% VAT, "
               "except on DLD fees and mortgage registration.")


def no_estimate(sales: pd.DataFrame, d: dict, home: tuple) -> None:
    found, _ = find_comps(sales, *home)
    with st.container(border=True):
        st.badge("No estimate", color="gray", icon=":material/search_off:")
        st.subheader("Not enough similar sales", anchor=False)
        st.markdown(
            f"Found {len(found)} {describe_home(d['property_type'], d['bedrooms'])} in {d['area']} within "
            f"{config.SIZE_TOLERANCE:.0%} of {d['size_sqft']:,.0f} sqft; at least {config.MIN_COMPS} are needed. "
            "Check the size against the typical one in the sidebar, or try a nearby area."
        )


# ---------------------------------------------------------------------------
# Pipeline view
# ---------------------------------------------------------------------------

REPORT_VIEW = {  # what fits on a laptop screen without scrolling sideways; the download has every column
    "deal_id": st.column_config.TextColumn("Deal", pinned=True),
    "risk": st.column_config.TextColumn("Risk", help="Risk of a valuation below the agreed price."),
    "area": "Area",
    "building": st.column_config.TextColumn("Building", width=130, help="Only when the CSV names one."),
    "price": "Price",
    "price_vs_estimate": st.column_config.Column(
        "vs estimate", help="How far the agreed price is above (+) or below (−) the estimated valuation."),
    "short_median": st.column_config.Column(
        "Short if typical", help="Cash the buyer would lack at the typical valuation."),
    "short_p25": st.column_config.Column(
        "Short if low", help="Cash the buyer would lack at the low valuation."),
    "confidence": "Confidence",
}

CANT_ASSESS = "Can't assess: "  # prefix batch.py puts on notes for deals with bad inputs
MAX_NOTES = 10  # a longer list stays in the downloaded report

REPORT_FORMATS = {
    "price": "{:,.0f}",
    "price_vs_estimate": "{:+.1%}",
    "short_median": "{:,.0f}",
    "short_p25": "{:,.0f}",
}


def pipeline_notes(report: pd.DataFrame) -> list[str]:
    """One line per deal with a note: outside Sooner's range, building not found, or not assessed."""
    lines = []
    for row in report[report["notes"].fillna("") != ""].itertuples():
        note = row.notes.removeprefix(CANT_ASSESS)
        if row.risk == "Unknown":
            note = "Not assessed: " + note
        lines.append(f"{row.deal_id} · {row.area} · {note[:1].upper()}{note[1:]}")
    if len(lines) > MAX_NOTES:
        lines = [*lines[:MAX_NOTES], f"{len(lines) - MAX_NOTES} more in the downloaded report"]
    return lines


def show_batch(sales: pd.DataFrame, settings: dict) -> None:
    st.header("Pipeline", anchor=False)
    purpose = "Every deal in a CSV export, sorted by risk of a low valuation."
    intro = st.empty()  # says which file is shown, once it has been read
    intro.caption(purpose)

    with st.container(border=True):
        left, right = st.columns([3, 1], vertical_alignment="center")
        upload = left.file_uploader("Pipeline CSV", type="csv", label_visibility="collapsed")
        right.download_button("CSV template", config.EXAMPLE_PIPELINE_PATH.read_bytes(),
                              file_name="pipeline_example.csv", mime="text/csv",
                              icon=":material/download:", width="stretch")
        st.caption(f"Columns: {', '.join(REQUIRED_COLUMNS)}; building is optional. Sizes in sqft. "
                   "Bedrooms can be 'studio'. Shorthands such as JVC and JLT work.")

    try:
        deals = read_deals(upload or config.EXAMPLE_PIPELINE_PATH)
    except ValueError as error:  # also covers unreadable files: pandas' parse errors are ValueErrors
        st.error(f"Couldn't read the CSV. {error}", icon=":material/error:")
        return
    if upload is None:
        intro.caption(f"{purpose} Showing the example pipeline ({len(deals)} deals) until you upload your own.")
    else:
        intro.caption(f"{purpose} Showing {upload.name} ({len(deals):,} deals).")
    with st.spinner(f"Checking {len(deals):,} deals..."):
        report = assess_deals(sales, deals, **settings)
    assessed = report[report["risk"] != "Unknown"]

    # Headline numbers, counting only deals Sooner can fund
    s = pipeline_summary(report)
    with st.container(border=True):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Deals", s["deals"])
        c1.caption(f"{s['assessed']} assessed" + (f", {s['deals'] - s['assessed']} not (see Notes)"
                                                  if s["deals"] > s["assessed"] else ""))
        c2.metric("High risk", s["high"])
        c2.caption(f"{s['medium']} more at Medium")
        c3.metric("Could fail if valued low", s["could_fail"],
                  help="Deals where the buyer would be short of cash at the low valuation.")
        c3.caption(f"{aed(s['short_total'])} short in total")
        c4.metric("Deposits at risk", aed_short(s["deposits_at_risk"]),
                  help=f"Form F deposits ({config.FORM_F_DEPOSIT_SHARE:.0%} of the price) on the deals that "
                       "could fail. Buyers can lose them if a sale falls through.")
        c4.caption(f"{config.FORM_F_DEPOSIT_SHARE:.0%} of the price on those deals")
    st.caption(f"Totals count the {s['eligible']} assessed deals in Sooner's price range, "
               f"AED {config.MIN_PRICE_AED:,} to {config.MAX_PRICE_AED:,}.")

    st.subheader("Deals by risk", anchor=False)
    view = assessed[list(REPORT_VIEW)]
    styled = (view.style
              .format(REPORT_FORMATS, na_rep="–")
              .map(lambda level: RISK_TINT.get(level, ""), subset=["risk"]))
    rows_shown = min(len(view), 20)  # show every row of a small pipeline without scrolling
    st.dataframe(styled, hide_index=True, width="stretch", height=35 * (rows_shown + 1) + 3,
                 column_config=REPORT_VIEW)
    st.caption("Amounts in AED. Click a column header to sort.")
    notes = pipeline_notes(report)
    if notes:
        st.markdown("**Notes**  \n" + "  \n".join(notes))
    st.download_button("Download report (CSV)", report.to_csv(index=False).encode("utf-8"),
                       file_name="valuation_gap_report.csv", mime="text/csv", icon=":material/download:")

    if not assessed.empty:
        st.subheader("Advisor note", anchor=False)
        pick = st.selectbox("Deal", assessed.index,
                            format_func=lambda i: f"{assessed.at[i, 'deal_id']} · {assessed.at[i, 'area']} · "
                                                  f"{assessed.at[i, 'risk']} risk")
        row = assessed.loc[pick]
        color, icon = RISK_STYLE[row["risk"]]
        with st.container(border=True):
            st.badge(f"{row['risk']} risk", color=color, icon=icon)
            st.markdown(f"**{row['deal_id']}** · {row['area']} · {aed(row['price'])}")
            st.markdown(row["advisor_note"])


# ---------------------------------------------------------------------------
# Method view
# ---------------------------------------------------------------------------

ACCURACY = pd.DataFrame(  # from the backtest (python -m radar.backtest)
    {"Share of sales": [0.32, 0.43, 0.22, 0.03],
     "Median error": [0.058, 0.078, 0.173, None],
     "Within ±10%": [0.74, 0.59, 0.33, None],
     "Inside low–high range": [0.43, 0.50, 0.53, None]},
    index=pd.Index(["High", "Medium", "Low", "No estimate"], name="Confidence"),
)


def assumptions_table() -> pd.DataFrame:
    """Every assumption, read from config.py so the page can't drift from the code."""
    rows = {
        "Eligible homes": f"Ready freehold, AED {config.MIN_PRICE_AED:,} to {config.MAX_PRICE_AED:,}",
        "Sooner support": f"Closing fees up to {config.SOONER_MAX_SHARE:.0%} of the home's value, "
                          f"max AED {config.SOONER_CAP_AED:,}",
        "Sooner repayment": f"{config.SOONER_TERM_MONTHS} months, flat {config.SOONER_FEE_MIN:.0%} to "
                            f"{config.SOONER_FEE_MAX:.0%} a year ({config.SOONER_FEE_DEFAULT:.0%} by default)",
        "Value for the 10% limit": "Agreed price by default, switchable to valuation (to confirm with Sooner)",
        "Bank loan": f"{config.DEFAULT_LTV:.0%} of the lower of price and valuation",
        "Form F deposit": f"{config.FORM_F_DEPOSIT_SHARE:.0%} of the price",
        **{f"Fee: {name}": basis for name, basis in FEE_BASIS.items()},
        "VAT": f"{config.VAT_RATE:.0%}, except on DLD fees and mortgage registration",
        "Similar sales": f"Same area, type and bedrooms; size within {config.SIZE_TOLERANCE:.0%}; same building "
                         f"when it has {config.MIN_PROJECT_COMPS}+ sales",
        "Recency": f"A sale's weight halves every {config.RECENCY_HALF_LIFE_DAYS} days",
    }
    return pd.DataFrame({"Value": list(rows.values())}, index=pd.Index(list(rows), name="Assumption"))


def show_method(sales: pd.DataFrame) -> None:
    st.header("Method", anchor=False)
    st.caption("What the tool is for, how the estimate is made, what it assumes and how accurate it is.")

    st.subheader("The problem", anchor=False)
    st.markdown(
        f"UAE banks lend on the lower of the agreed price and their own valuation. When the valuation comes in "
        f"below the price, the loan shrinks and the buyer has to cover the difference in cash: at "
        f"{config.DEFAULT_LTV:.0%} loan-to-value, every AED 100,000 of gap costs the buyer "
        f"AED {config.DEFAULT_LTV * 100_000:,.0f} more at completion.\n\n"
        "Sooner pays a first-time buyer's closing fees but not the down payment, so the whole gap lands on the "
        "buyer, and Sooner's buyers are cash-tight by design. If they can't raise it, the sale falls through, the "
        "buyer can lose their Form F deposit and Sooner loses the deal. Checking the price against recent sales "
        "before the Form F is signed leaves time to get a pre-valuation, renegotiate or plan the cash."
    )

    st.subheader("How the estimate works", anchor=False)
    st.markdown(
        f"1. **Similar sales.** DLD sales of ready freehold homes in the same area, with the same type and "
        f"bedrooms and a size within {config.SIZE_TOLERANCE:.0%}. If the chosen building has at least "
        f"{config.MIN_PROJECT_COMPS}, only those are used.\n"
        f"2. **Recency.** A sale's weight halves every {config.RECENCY_HALF_LIFE_DAYS} days.\n"
        "3. **Valuation range.** The weighted 25th, 50th and 75th percentiles of price per sqft, times the "
        "home's size, give the low, typical and high valuation.\n"
        f"4. **Confidence.** High needs {config.HIGH_CONFIDENCE_COMPS}+ similar sales whose middle half of prices "
        f"spans no more than {config.HIGH_CONFIDENCE_SPREAD:.0%}; Medium needs {config.MEDIUM_CONFIDENCE_COMPS}+ "
        f"within {config.MEDIUM_CONFIDENCE_SPREAD:.0%}; anything else is Low. Fewer than {config.MIN_COMPS} "
        "similar sales gives no estimate.\n"
        "5. **Risk.** How far the agreed price sits above the typical valuation, plus "
        f"{config.CONFIDENCE_BUFFER['Medium'] * 100:.0f} points at Medium confidence or "
        f"{config.CONFIDENCE_BUFFER['Low'] * 100:.0f} at Low. Below {config.MEDIUM_RISK_FROM:.0%} is Low risk, "
        f"from {config.HIGH_RISK_FROM:.0%} High, Medium in between.\n"
        "6. **Cash.** For each valuation, the loan is the loan-to-value times the lower of price and valuation, "
        "closing fees follow Sooner's calculator, Sooner pays them within its limits, and the buyer pays the "
        "rest of the price."
    )

    st.subheader("Accuracy", anchor=False)
    st.markdown(
        "Each sale in the last 60 days of data (4,411 sales) was estimated from the sales registered before it "
        "and compared with the price paid. Accuracy rises with confidence, and about half of prices land inside "
        "the low-to-high range, as they should. Comparing within the same building roughly halves the error "
        "(5.8% against 11.0% across the area). Sale prices stand in for bank valuations, which DLD does not publish."
    )
    st.table(ACCURACY.style.format("{:.0%}", na_rep="–")
             .format("{:.1%}", subset=["Median error"], na_rep="–"))

    st.subheader("Assumptions", anchor=False)
    st.table(assumptions_table())
    st.caption("Defined in radar/config.py. Bank loan, Sooner's fee and the value basis can also be changed under "
               "Assumptions in the Deal and Pipeline views.")

    st.subheader("Limitations", anchor=False)
    st.markdown(
        "- An estimate from past sales, not a bank valuation. Valuers inspect the home: floor, view and condition "
        "all move the number, and the DLD data has none of them.\n"
        "- Checked against sale prices, because DLD doesn't publish valuations. Banks can be more conservative "
        "than the market.\n"
        f"- Covers {sales['date'].min():%b} to {sales['date'].max():%b %Y}. Older years would fill the "
        f"{config.LOOKBACK_MONTHS}-month window without code changes.\n"
        "- Rare homes, such as large apartments or villas in small communities, get Low confidence or no estimate.\n"
        "- One loan-to-value for every buyer, no credit checks, and no ongoing costs such as interest."
    )

    st.subheader("Glossary", anchor=False)
    st.markdown(
        "- **Valuation:** what the bank's valuer says the home is worth. The bank lends on the lower of this "
        "and the agreed price.\n"
        "- **Low, typical and high valuation:** the 25th, 50th and 75th percentiles of similar sales, scaled to "
        "the home's size.\n"
        "- **Loan-to-value:** the share of the home's value the bank lends.\n"
        "- **Down payment:** the part of the price the buyer pays from their own cash.\n"
        "- **Closing fees:** DLD, agency, bank and other fees at transfer, paid by Sooner within its limits and "
        "repaid monthly over five years.\n"
        "- **Form F:** the Dubai sale contract. The buyer's deposit is at risk if they can't complete.\n"
        "- **Pre-valuation:** a bank valuation arranged before the contract is signed."
    )


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

def data_footer(sales: pd.DataFrame) -> None:
    source = ("All areas in the DLD data." if config.PROCESSED_PATH.exists()
              else f"Sample data: the {config.SAMPLE_AREAS} busiest areas for apartments and for villas.")
    st.divider()
    st.caption(
        f"{len(sales):,} DLD sales of ready freehold homes, {sales['date'].min():%d %b %Y} to "
        f"{sales['date'].max():%d %b %Y}. {source} Estimates come from past sales, not bank valuations. "
        "Independent demo for Sooner (joinsooner.com), not an official Sooner product."
    )


def main() -> None:
    st.markdown(PAGE_CSS, unsafe_allow_html=True)
    sales = get_sales()
    view = sidebar_header()
    if view == "Deal":
        deal = deal_inputs(sales)
        settings = settings_inputs()
        show_deal(sales, deal, settings)
    elif view == "Pipeline":
        settings = settings_inputs()
        show_batch(sales, settings)
    else:
        show_method(sales)
    data_footer(sales)


main()
