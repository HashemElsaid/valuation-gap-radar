"""Valuation Gap Radar: the Streamlit app.

Run it from the project root:

    streamlit run app.py

Two modes, picked at the top of the sidebar: check one deal, or upload a CSV
and check many deals at once. All the maths lives in the radar/ package. This
file only collects inputs and shows results, in plain words: every number has
a one-line explanation and a help tooltip, and the page ends with a glossary.
The app shows sizes and prices per sqft, as Dubai listings do; the engine works
in sqm, so the conversion happens here at the edge.

Colours and fonts are set in .streamlit/config.toml (styled after joinsooner.com).
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
# backgrounds: similar sales are blue, this deal is orange. Sooner's lime is
# kept for highlights only, because as a line or dot on white it can't be seen.
COLORS = {
    "light": {"comps": "#2a78d6", "deal": "#eb6834", "surface": "#ffffff", "band": 0.2,
              "ink": "#0e0d0d", "muted": "#6e6e6e", "bad": "#a82828",
              "buyer": "#4a4646", "buyer_ink": "#ffffff"},
    "dark": {"comps": "#3987e5", "deal": "#d95926", "surface": "#0e0d0d", "band": 0.4,
             "ink": "#f4f4f4", "muted": "#9f9e9e", "bad": "#ff8a8a",
             "buyer": "#cfcfcf", "buyer_ink": "#0e0d0d"},
}
# Sooner's lime highlighter. Text on it is always near-black, as on joinsooner.com,
# so it stays readable in dark mode too.
LIME = "background-color: #e9fe0f; color: #0e0d0d; font-weight: 600"

# Each risk level has a colour, an icon and a plain headline, so colour is never the only cue.
RISK_STYLE = {
    "Low": ("green", ":material/check_circle:"),
    "Medium": ("orange", ":material/warning:"),
    "High": ("red", ":material/error:"),
}
RISK_HEADLINE = {
    "High": "The bank is likely to value this home below the price",
    "Medium": "The bank may value this home a little below the price",
    "Low": "The price is in line with what similar homes sold for",
}
RISK_TINT = {  # see-through, so it works on light and dark backgrounds
    "High": "background-color: rgba(208, 59, 59, 0.16)",
    "Medium": "background-color: rgba(232, 137, 12, 0.18)",
    "Low": "background-color: rgba(12, 163, 12, 0.13)",
}

SCENARIO_NAMES = {"P25": "If the bank values low", "Median": "If it values typical", "P75": "If it values high"}

SCENARIO_ROWS = {
    "Bank's valuation": "valuation",
    "Bank loan": "loan",
    "Down payment (buyer pays)": "down_payment",
    "Closing fees": "closing_costs",
    "Paid by Sooner": "sooner_support",
    "Cash the buyer needs": "cash_needed",
    "Extra cash because of the valuation": "extra_cash_from_gap",
    "Buyer is short by": "shortfall",
    "Monthly repayment to Sooner": "monthly_repayment",
}

FEE_BASIS = {
    "Dubai Land Department": f"{config.DLD_RATE:.0%} of the price + AED {config.DLD_ADMIN_AED}",
    "DLD title deed": "Flat fee",
    "Agency commission": f"{config.AGENCY_RATE:.0%} of the price + VAT",
    "Bank arrangement fee": f"{config.BANK_ARRANGEMENT_RATE:.0%} of the loan + VAT",
    "Mortgage registration": f"{config.MORTGAGE_REGISTRATION_RATE:.2%} of the loan "
                             f"+ AED {config.MORTGAGE_REGISTRATION_ADMIN_AED}",
    "Valuation": "Flat fee + VAT",
    "Trustee": "Flat fee + VAT",
    "NOC": "Developer's no-objection certificate + VAT",
    "Conveyancing": "Flat fee + VAT",
}

GLOSSARY = """
- **Valuation:** what the bank's valuer says the home is worth. The bank lends on the
  *lower* of this and the agreed price.
- **Low valuation (down-valuation):** when the valuation comes in below the agreed price.
  The loan shrinks, so the buyer has to bring more cash.
- **Likely range (low, typical, high):** where most valuations should land, based on similar
  sales. A quarter of similar homes sold below "low", half below "typical", three quarters
  below "high".
- **Similar sales:** real DLD sales in 2026 of homes in the same area, with the same type and
  bedrooms and a size within 20%. Recent sales count more.
- **How sure we are:** High, Medium or Low, based on how many similar sales there are and how
  much their prices vary. Picking the building usually raises it.
- **Loan-to-value (LTV):** the share of the home's value the bank lends: 80% for an expat's
  first home under AED 5M.
- **Down payment:** the part of the price the buyer pays from their own cash.
- **Closing fees:** DLD, agency, bank and other fees paid at transfer. Sooner pays them, up to
  10% of the home's value and AED 500,000, and the buyer repays Sooner monthly over 5 years.
- **Form F:** the Dubai sale contract between buyer and seller. The buyer's deposit (usually
  10%) is at risk if they can't complete.
- **Pre-valuation:** asking the bank to value the home before signing, so there are no surprises.
"""


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


def highlight(text: str) -> str:
    """Wrap fixed text in the lime highlighter. Only ever pass our own text, never user input."""
    return f'<span style="{LIME}; padding: 0 0.15em; border-radius: 3px">{text}</span>'


def home_label(property_type: str, bedrooms: int) -> str:
    """'Studio apartment', '2-bed apartment', '3-bed villa'."""
    kind = property_type.lower()
    return f"Studio {kind}" if bedrooms == 0 else f"{bedrooms}-bed {kind}"


def page_intro(why: str, steps: list[tuple[str, str, str]]) -> None:
    """Why the page matters to Sooner, then numbered steps explaining how to use it."""
    with st.container(border=True):
        st.markdown(f":material/lightbulb: **Why this matters**  \n{why}")
        for column, (icon, title, text) in zip(st.columns(len(steps)), steps):
            column.markdown(f"{icon} **{title}**")
            column.caption(text)


def glossary() -> None:
    with st.expander("What the words on this page mean", icon=":material/menu_book:"):
        st.markdown(GLOSSARY)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def sidebar_header() -> str:
    """App name, purpose and the mode switch. Returns the chosen mode."""
    sb = st.sidebar
    sb.markdown(f"### Valuation Gap {highlight('Radar')}", unsafe_allow_html=True)
    sb.caption("Will the bank value the home below the price? Check before the buyer signs.")
    # ?mode=pipeline in the URL opens the many-deals mode directly, e.g. for a shared link.
    default_mode = "Many deals" if st.query_params.get("mode") == "pipeline" else "One deal"
    return sb.segmented_control("Mode", ["One deal", "Many deals"], default=default_mode, required=True,
                                label_visibility="collapsed", width="stretch")


def deal_inputs(sales: pd.DataFrame) -> dict:
    """The home and the deal. Dropdowns only offer what has sales, with counts."""
    sb = st.sidebar
    sb.subheader("1. The home")
    area_counts = sales["area"].value_counts()
    areas = sorted(area_counts.index)
    area = sb.selectbox("Area", areas, index=areas.index(area_counts.index[0]),
                        format_func=lambda a: f"{a} ({area_counts[a]:,} sales)",
                        help="The community, as the Dubai Land Department names it. The number is how "
                             "many sales we have there: more sales, better estimates.")

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
        help="Pick it if you know it. Homes in the same building sell for similar prices, so the "
             "estimate gets much sharper.",
    )
    size_sqft = sb.number_input("Size (sqft)", min_value=150, max_value=30_000, value=750, step=10,
                                help="The home's size from the listing or title deed, in square feet.")
    typical = homes["size_sqm"].median() * config.SQFT_PER_SQM
    sb.caption(f"Typical size here: {typical:,.0f} sqft")

    sb.subheader("2. The deal")
    price = sb.number_input("Agreed price (AED)", min_value=100_000, value=1_000_000, step=10_000,
                            help="The price the buyer and seller agreed, as it will appear on the Form F.")
    sb.caption(aed(price))  # number inputs can't show thousands separators, so repeat it here
    cash = sb.number_input("Buyer's cash (AED)", min_value=0, value=250_000, step=5_000,
                           help="All the cash the buyer can bring at completion, including the "
                                "down payment. Sooner pays the closing fees separately.")
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
    """The assumptions that apply to every deal, in both modes."""
    with st.sidebar.expander("Assumptions", icon=":material/tune:"):
        ltv = st.slider("Bank loan, % of the home's value", 50, 85, round(config.DEFAULT_LTV * 100), 5,
                        help="Loan-to-value. 80% is the cap for an expat's first home under AED 5M; "
                             "use less for a second home or a home over AED 5M.")
        # round() because 0.07 * 100 is 7.000000000000001 in floating point
        fee = st.slider("Sooner's yearly fee (%)", round(config.SOONER_FEE_MIN * 100, 1),
                        round(config.SOONER_FEE_MAX * 100, 1), round(config.SOONER_FEE_DEFAULT * 100, 1), 0.5,
                        help="Sooner's flat fee per year. It only changes the monthly repayment.")
        value_basis = st.radio("Sooner's 10% limit uses the", ["price", "valuation"],
                               format_func=str.capitalize,
                               help="Sooner covers fees up to 10% of the home's value. Which value counts "
                                    "is still to be confirmed with Sooner.")
    return {"ltv": ltv / 100, "fee_rate": fee / 100, "value_basis": value_basis}


# ---------------------------------------------------------------------------
# One deal
# ---------------------------------------------------------------------------

def show_deal(sales: pd.DataFrame, d: dict, settings: dict) -> None:
    st.markdown(f"## Will the bank value this home {highlight('below the price')}?", unsafe_allow_html=True)
    page_intro(
        "Sooner pays the buyer's fees, **not the down payment**. If the bank values the home below the price, "
        "the bank lends less and the buyer must cover the gap from their own cash. Sooner's buyers rarely have "
        "that cash spare, so the deal can fail: the buyer can lose their Form F deposit, and Sooner loses the "
        "deal. This check spots the risk **before** the Form F is signed, while there's still time to fix it.",
        [
        (":material/edit_note:", "1. Describe the deal", "Fill in the home, the price and the buyer's cash "
                                                         "in the panel on the left."),
        (":material/query_stats:", "2. We compare similar sales", "Real DLD sales of similar homes show what "
                                                                  "a bank valuer is likely to say."),
        (":material/account_balance_wallet:", "3. See the cash at stake", "A low valuation means a smaller loan. "
                                                                         "We show how much more cash the buyer needs."),
        ],
    )

    building = d["project"] or "Any building"
    st.subheader(f"{home_label(d['property_type'], d['bedrooms'])} in {d['area']}")
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
        glossary()
        return

    risk = gap_risk(d["price"], est)
    scenarios = scenario_table(d["price"], est.valuations, d["cash_available"], **settings)
    note = advisor_note(area=d["area"], property_type=d["property_type"], bedrooms=d["bedrooms"],
                        size_sqm=d["size_sqm"], price=d["price"], cash_available=d["cash_available"],
                        estimate=est, risk=risk, scenarios=scenarios, include_actions=False)

    verdict_card(d, est, risk, scenarios)
    who_pays(d, est, settings)
    left, right = st.columns([3, 2])
    with left:
        text_card("In plain words", ":material/chat:", note)
    with right:
        steps = "\n".join(f"- {step}" for step in next_steps(est, risk, scenarios))
        text_card("What to do next", ":material/checklist:", steps)

    cash_tab, comps_tab, fees_tab = st.tabs([
        ":material/payments: Cash the buyer needs",
        ":material/home_work: Similar homes sold",
        ":material/receipt_long: Closing fees",
    ])
    with cash_tab:
        cash_table(scenarios, settings)
    with comps_tab:
        comparable_sales(est, d)
    with fees_tab:
        closing_fee_lines(d, settings)
    glossary()


def verdict_card(d: dict, est, risk, scenarios: pd.DataFrame) -> None:
    """The answer first: risk level, where the price sits, and the cash at stake."""
    color, icon = RISK_STYLE[risk.level]
    by_name = scenarios.set_index("name")
    low, typical = by_name.loc["P25"], by_name.loc["Median"]
    direction = "above" if risk.premium >= 0 else "below"
    headline = RISK_HEADLINE[risk.level]
    if risk.level == "Low" and risk.premium <= 0:
        headline = "The price is at or below what similar homes sold for"

    with st.container(border=True):
        st.badge(f"{risk.level} risk of a low valuation", color=color, icon=icon)
        st.markdown(f"### {headline}")
        st.markdown(f"We estimate the bank will value it at about **{aed_round(est.value_median)}**. "
                    f"The agreed price of {aed(d['price'])} is **{abs(risk.premium):.0%} {direction}** that.")
        st.altair_chart(range_chart(est, d["price"], colors()), width="stretch")
        st.caption("The bar is the likely range of the bank's valuation, based on similar sales. "
                   "The orange line is the agreed price.")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Likely bank valuation", aed_short(est.value_median),
                  help="The typical price per sqft of similar homes, times this home's size. "
                       "Recent sales count more.")
        c1.caption(f"Probably between {aed_short(est.value_p25)} and {aed_short(est.value_p75)}")
        c2.metric("Buyer would be short by", aed_short(low["shortfall"]),
                  help="If the bank values at the low end of the range: the cash needed at completion "
                       "minus the cash the buyer has.")
        c2.caption(f"if the bank values low ({aed_short(low['valuation'])})" if low["shortfall"] > 0
                   else f"Their {aed(d['cash_available'])} is enough, even if the bank values low")
        c3.metric("Extra cash needed", aed_short(typical["extra_cash_from_gap"]),
                  help="How much more the buyer pays than if the bank valued the home at the agreed price.")
        c3.caption(f"if the bank values typical ({aed_short(typical['valuation'])})")
        c4.metric("How sure we are", est.confidence,
                  help="High: many similar sales that agree closely. Low: few sales, or prices that vary "
                       "a lot. Picking the building usually helps.")
        c4.caption(comps_source(est, d))

        why = (f"Why {risk.level.lower()} risk: the price is {risk.premium:+.1%} against our estimate"
               + (f", plus {risk.buffer * 100:.0f} points because we're less sure" if risk.buffer else "")
               + f". We call {config.MEDIUM_RISK_FROM:.0%} or more Medium and {config.HIGH_RISK_FROM:.0%} "
                 "or more High.")
        st.caption(why)


def who_pays(d: dict, est, settings: dict) -> None:
    """Who pays what, if the bank agrees with the price and if it values low.

    This is the heart of the problem: Sooner covers the fees, but a low
    valuation grows the buyer's own part, which Sooner can't cover.
    """
    split = scenario_table(
        d["price"],
        {"If the bank agrees with the price": d["price"],
         f"If the bank values low ({aed_short(est.value_p25)})": est.value_p25},
        d["cash_available"], **settings,
    )
    agree, low = split.iloc[0], split.iloc[1]
    extra = low["cash_needed"] - agree["cash_needed"]

    with st.container(border=True):
        st.markdown(":material/account_balance: **Who pays for this home**")
        st.altair_chart(who_pays_chart(split, d["cash_available"], colors()), width="stretch")
        text = (f"The bank lends {settings['ltv']:.0%} of the lower of the price and its valuation. The buyer pays "
                "the rest from their own cash, and Sooner pays the fees on top. ")
        if extra > 0:
            text += (f"If the bank values low, its loan shrinks and **the buyer's part grows by {aed(extra)}**. "
                     "Sooner can't cover that part.")
        else:
            text += "Even at the low end of the likely range, the valuation is at or above the price, so the buyer's part doesn't grow."
        if low["shortfall"] > 0:
            deposit = config.FORM_F_DEPOSIT_SHARE * d["price"]
            text += (f" This buyer would be **{aed(low['shortfall'])} short**. If they can't find it, the deal can "
                     f"fail and they could lose their Form F deposit (usually "
                     f"{config.FORM_F_DEPOSIT_SHARE:.0%}: about {aed_round(deposit)}).")
        st.markdown(text)


def who_pays_chart(split: pd.DataFrame, cash: float, c: dict) -> alt.Chart:
    """One bar per scenario: the bank's loan, the buyer's own cash, any shortfall, and Sooner's fees."""
    parts = ["Bank loan", "Buyer's own cash", "Buyer is short", "Fees paid by Sooner"]
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
    y = alt.Y("scenario:N", sort=split["name"].tolist(), title=None,
              axis=alt.Axis(labelLimit=320, labelFontSize=13, ticks=False, domain=False,
                            labelPadding=10, labelColor=c["ink"]))

    bars = alt.Chart(data).mark_bar(size=24, cornerRadius=3, stroke=c["surface"], strokeWidth=2).encode(
        y=y, x=alt.X("start:Q", scale=x_scale, axis=None), x2="end:Q",
        color=alt.Color("part:N", scale=alt.Scale(domain=parts, range=fills),
                        legend=alt.Legend(orient="top", title=None, labelColor=c["ink"], symbolType="square")),
        tooltip=[alt.Tooltip("scenario:N", title="Scenario"), alt.Tooltip("part:N", title="Part"),
                 alt.Tooltip("amount:Q", title="AED", format=",.0f")],
    )
    # Write the amount inside a segment only when it's wide enough to hold it.
    labels = alt.Chart(data[data["amount"] / total > 0.08]).mark_text(fontSize=11, fontWeight=600).encode(
        y=y, x=alt.X("mid:Q", scale=x_scale, axis=None), text="label:N", color=alt.Color("ink:N", scale=None),
    )
    # A fixed height per row (not for the whole chart) keeps the two bars apart.
    return alt.layer(bars, labels).properties(height=alt.Step(46)).configure_view(stroke=None)


def next_steps(est, risk, scenarios: pd.DataFrame) -> list[str]:
    """A short checklist for the advisor, matching the risk level."""
    by_name = scenarios.set_index("name")
    low, typical = by_name.loc["P25"], by_name.loc["Median"]
    steps = []
    if risk.level == "High":
        steps += [
            "Ask the bank for a **pre-valuation before** the buyer signs the Form F.",
            f"Try to negotiate the price closer to **{aed_round(est.value_median)}**.",
            "Add a **Form F clause** that returns the deposit if the valuation comes in low.",
        ]
    elif risk.level == "Medium":
        if typical["extra_cash_from_gap"] > 0:
            steps.append(f"Check the buyer can cover **{aed(typical['extra_cash_from_gap'])}** extra.")
        steps.append("Consider a bank **pre-valuation** before the Form F is signed.")
    else:
        steps.append("Go ahead as normal: a low valuation looks unlikely.")
    if low["shortfall"] > 0:
        steps.append(f"If the bank values at the low end, the buyer would be **{aed(low['shortfall'])} short**. "
                     "Check they could find it.")
    if est.confidence == "Low" and est.basis == "area":
        steps.append("Pick the **building** in the left panel to make this estimate much sharper.")
    return steps


def comps_source(est, d: dict) -> str:
    spread = f"prices vary ±{est.spread / 2:.0%}"
    if est.basis == "project":
        return f"{est.n_comps:,} similar sales in {est.comps['project'].iloc[0]}; {spread}"
    if d["project"]:
        return f"{est.n_comps:,} similar sales across the area (too few in {d['project']}); {spread}"
    return f"{est.n_comps:,} similar sales across the area; {spread}"


def range_chart(est, price: float, c: dict) -> alt.Chart:
    """A strip showing where the agreed price sits against the likely valuation range.

    Blue band = low to high valuation, blue tick = typical, orange line = the
    agreed price. Labels that would overlap are merged or dropped.
    """
    lo, mid, hi = est.value_p25, est.value_median, est.value_p75
    left, right = min(lo, price), max(hi, price)
    pad = (right - left) * 0.12
    start, end = left - pad, right + pad
    scale = alt.Scale(domain=[start, end])

    def at(value):  # position across the strip, 0 to 1
        return (value - start) / (end - start)

    band = alt.Chart(pd.DataFrame({"lo": [lo], "hi": [hi]})).mark_rect(
        color=c["comps"], opacity=c["band"], cornerRadius=4
    ).encode(
        x=alt.X("lo:Q", scale=scale, axis=None), x2="hi:Q", y=alt.value(34), y2=alt.value(54),
        tooltip=[alt.Tooltip("lo:Q", title="Low valuation (AED)", format=",.0f"),
                 alt.Tooltip("hi:Q", title="High valuation (AED)", format=",.0f")],
    )
    typical_tick = alt.Chart(pd.DataFrame({"v": [mid]})).mark_rule(color=c["comps"], strokeWidth=2).encode(
        x=alt.X("v:Q", scale=scale, axis=None), y=alt.value(30), y2=alt.value(58),
        tooltip=[alt.Tooltip("v:Q", title="Typical valuation (AED)", format=",.0f")],
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
        labels.append(label(lo, f"Low {aed_short(lo)}", "left", 66, c["muted"]))
        labels.append(label(hi, f"High {aed_short(hi)}", "right", 66, c["muted"]))
        if min(at(mid) - at(lo), at(hi) - at(mid)) > 0.15:  # room for the typical label in between
            labels.append(label(mid, f"Typical {aed_short(mid)}", "center", 66, c["muted"]))

    return (alt.layer(band, typical_tick, price_line, *labels)
            .properties(height=86)
            .configure_view(stroke=None))


def text_card(title: str, icon: str, body: str) -> None:
    with st.container(border=True, height="stretch"):
        st.markdown(f"{icon} **{title}**")
        st.markdown(body)


def cash_table(scenarios: pd.DataFrame, settings: dict) -> None:
    st.markdown(
        f"The bank lends **{settings['ltv']:.0%} of the lower of the price and its valuation**. So a lower "
        "valuation means a smaller loan, and the buyer pays the difference. Sooner pays the closing fees "
        f"(up to {config.SOONER_MAX_SHARE:.0%} of the {settings['value_basis']})."
    )
    table = scenarios.set_index("name")[list(SCENARIO_ROWS.values())].T
    table.index = list(SCENARIO_ROWS)
    table = table.rename(columns=SCENARIO_NAMES)
    bad = colors()["bad"]
    styled = (table.style.format("AED {:,.0f}")
              .map(lambda v: LIME, subset=pd.IndexSlice[["Paid by Sooner"], :])
              .map(lambda v: f"color: {bad}; font-weight: 600" if v > 0 else "",
                   subset=pd.IndexSlice[["Buyer is short by"], :])
              .map(lambda v: "font-weight: 600", subset=pd.IndexSlice[["Cash the buyer needs"], :]))
    st.table(styled)
    st.caption(f"The buyer repays Sooner over {config.SOONER_TERM_MONTHS} months with a flat yearly fee of "
               f"{settings['fee_rate']:.1%}. The low, typical and high valuations come from similar sales.")


def comparable_sales(est, d: dict) -> None:
    st.markdown("Each dot is a **real sale of a similar home**: same area, type and bedrooms, and a size "
                "within 20%. Higher dots sold for more per sqft. Faded dots are older and count less.")
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
            "Counts for", min_value=0, max_value=1, format="percent",
            help="How much this sale counts in the estimate. Halves every 4 months, so recent sales matter most."),
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
            alt.Tooltip("weight:Q", title="Counts for", format=".0%"),
        ],
    )

    refs = pd.DataFrame({
        "value": [median, deal_psf],
        "label": [f"Typical similar sale: AED {median:,.0f}/sqft", f"This deal: AED {deal_psf:,.0f}/sqft"],
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
    st.markdown("What the buyer would pay at transfer, **line by line, as on Sooner's calculator**. "
                "Sooner pays these up front, up to 10% of the home's value.")
    costs = closing_costs(d["price"], loan_amount(d["price"], d["price"], settings["ltv"]))
    lines = pd.DataFrame({"How it's worked out": [FEE_BASIS.get(k, "") for k in costs],
                          "Amount": list(costs.values())}, index=list(costs))
    lines.loc["Total"] = ["", sum(costs.values())]
    st.table(lines.style.format({"Amount": "AED {:,.0f}"})
             .map(lambda v: "font-weight: 600", subset=pd.IndexSlice[["Total"], :]))
    st.caption("If the bank values the home at the agreed price. Amounts include 5% VAT where it applies "
               "(not on DLD fees or mortgage registration).")


def no_estimate(sales: pd.DataFrame, d: dict, home: tuple) -> None:
    found, _ = find_comps(sales, *home)
    with st.container(border=True):
        st.badge("No estimate", color="gray", icon=":material/search_off:")
        st.markdown("### Not enough similar sales to estimate this one")
        st.markdown(
            f"We found {len(found)} {describe_home(d['property_type'], d['bedrooms'])} in {d['area']} within "
            f"{config.SIZE_TOLERANCE:.0%} of {d['size_sqft']:,.0f} sqft, and need at least {config.MIN_COMPS}. "
            "Check the size against the typical one shown on the left, or try a nearby area."
        )


# ---------------------------------------------------------------------------
# Many deals (batch) mode
# ---------------------------------------------------------------------------

REPORT_VIEW = {  # decision columns first, so they're visible without scrolling sideways
    "deal_id": st.column_config.TextColumn("Deal", pinned=True),
    "risk": st.column_config.TextColumn("Risk", help="Risk of a low valuation: High, Medium or Low."),
    "area": "Area",
    "price": "Price (AED)",
    "price_vs_estimate": st.column_config.Column(
        "Price vs estimate", help="How far the price is above (+) or below (−) our estimate."),
    "short_median": st.column_config.Column(
        "Short if typical (AED)", help="Cash the buyer would lack if the bank values at the typical estimate."),
    "short_p25": st.column_config.Column(
        "Short if low (AED)", help="Cash the buyer would lack if the bank values at the low end."),
    "confidence": st.column_config.TextColumn(
        "How sure", help="High: many similar sales that agree. Low: few sales, or prices that vary a lot."),
    "notes": st.column_config.TextColumn(
        "Notes", width="large", help="Anything to check: outside Sooner's price range, unknown area, "
                                     "too few similar sales."),
    "estimate": "Our estimate (AED)",
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
    st.markdown(f"## Check {highlight('many deals')} at once", unsafe_allow_html=True)
    page_intro(
        "Every deal where the buyer would be short of cash could fail at the bank valuation: Sooner loses the "
        "deal and the buyer can lose their deposit. This list shows which deals to act on first, **before** "
        "their Form F is signed.",
        [
            (":material/download:", "1. Get the template", "Download the example file below and see the columns."),
            (":material/table_edit:", "2. One row per deal", "Fill it in, or export your pipeline from the CRM "
                                                            "with the same columns."),
            (":material/upload_file:", "3. Upload it", "Every deal is checked, and the riskiest come first."),
        ],
    )

    with st.container(border=True):
        left, right = st.columns([3, 1], vertical_alignment="center")
        upload = left.file_uploader("Pipeline CSV", type="csv", label_visibility="collapsed")
        right.download_button("Download the template", config.EXAMPLE_PIPELINE_PATH.read_bytes(),
                              file_name="pipeline_example.csv", mime="text/csv",
                              icon=":material/download:", width="stretch")
        st.caption(f"Columns: {', '.join(REQUIRED_COLUMNS)}, and optionally building. Sizes in sqft; "
                   "bedrooms can be 'studio'; area shorthands like JVC, JLT and Marina work.")
    if upload is None:
        st.info("No file uploaded yet, so you're looking at the example pipeline of 12 deals.",
                icon=":material/info:")

    try:
        deals = read_deals(upload or config.EXAMPLE_PIPELINE_PATH)
    except ValueError as error:  # also covers unreadable files: pandas' parse errors are ValueErrors
        st.error(f"Couldn't read the CSV. {error}", icon=":material/error:")
        return
    with st.spinner(f"Checking {len(deals):,} deals..."):
        report = assess_deals(sales, deals, **settings)
    assessed = report[report["risk"] != "Unknown"]

    # Summary: what's at stake for Sooner and its buyers
    short_low = assessed[assessed["short_p25"] > 0]
    deposits = config.FORM_F_DEPOSIT_SHARE * short_low["price"].sum()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Deals checked", len(report), border=True, icon=":material/fact_check:")
    c1.caption(f"{len(assessed)} assessed, {len(report) - len(assessed)} couldn't be (see Notes)")
    c2.metric("High risk", int((report["risk"] == "High").sum()), border=True, icon=":material/error:")
    c2.caption(f"Plus {int((report['risk'] == 'Medium').sum())} at Medium risk")
    c3.metric("Could fail if valued low", len(short_low), border=True, icon=":material/trending_down:",
              help="Deals where the buyer would be short of cash if the bank values at the low end of the range.")
    c3.caption(f"Buyers {aed(short_low['short_p25'].sum())} short in total")
    c4.metric("Deposits at risk", aed_short(deposits), border=True, icon=":material/savings:",
              help=f"The Form F deposits (usually {config.FORM_F_DEPOSIT_SHARE:.0%} of the price) of the buyers "
                   "in those deals. If a deal fails, the buyer can lose it.")
    c4.caption(f"{config.FORM_F_DEPOSIT_SHARE:.0%} deposits across those {len(short_low)} deals")

    # Report, riskiest first
    st.subheader("Every deal, riskiest first")
    st.caption("Hover over a column name to see what it means. Scroll sideways for more columns.")
    view = report[list(REPORT_VIEW)].fillna({"confidence": "–"})
    styled = (view.style
              .format(REPORT_FORMATS, na_rep="–")
              .map(lambda level: RISK_TINT.get(level, ""), subset=["risk"]))
    rows_shown = min(len(view), 20)  # show every row of a small pipeline without scrolling
    st.dataframe(styled, hide_index=True, width="stretch", height=35 * (rows_shown + 1) + 3,
                 column_config=REPORT_VIEW)
    st.download_button("Download the full report (CSV)", report.to_csv(index=False).encode("utf-8"),
                       file_name="valuation_gap_report.csv", mime="text/csv", icon=":material/download:")

    # One deal's advisor note
    if not assessed.empty:
        st.subheader("Message for one deal")
        pick = st.selectbox("Pick a deal", assessed.index,
                            format_func=lambda i: f"{assessed.at[i, 'deal_id']}: {assessed.at[i, 'risk']} risk, "
                                                  f"{assessed.at[i, 'area']}")
        row = assessed.loc[pick]
        color, icon = RISK_STYLE[row["risk"]]
        with st.container(border=True):
            st.badge(f"{row['risk']} risk of a low valuation", color=color, icon=icon)
            st.markdown(f"### {row['deal_id']}: {row['area']}, {aed(row['price'])}")
            st.markdown(row["advisor_note"])
    glossary()


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
        "This is an estimate from past sales, not a bank valuation. "
        "Independent demo built for Sooner (joinsooner.com); not an official Sooner product."
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
