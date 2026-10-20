"""Smoke tests for the Streamlit app: each view renders without errors.

Uses Streamlit's AppTest, which runs app.py without a browser, so we can set
inputs and read what the page shows.
"""

from streamlit.testing.v1 import AppTest

from radar import config


def run_app(**query_params):
    at = AppTest.from_file(str(config.ROOT / "app.py"), default_timeout=60)
    at.query_params.update(query_params)
    return at.run()


def widget(widgets, label):
    return next(w for w in widgets if w.label == label)


def page_text(at):
    return " ".join(str(m.value) for m in at.markdown)


def headings(at):
    return [h.value for h in [*at.header, *at.subheader]]


def test_deal_view_leads_with_the_verdict():
    at = run_app()

    assert not at.exception
    assert "The agreed price is" in page_text(at)  # price against the estimated valuation
    assert "Who pays" in headings(at)
    assert len(at.tabs) == 3


def test_choosing_a_building_uses_its_sales():
    at = run_app()
    building = widget(at.sidebar.selectbox, "Building")
    building.set_value(building.options[1]).run()  # the busiest building in the area
    chosen = widget(at.sidebar.selectbox, "Building").value

    assert not at.exception
    assert any(f"sales in {chosen}" in c.value for c in at.caption)  # comps came from that building


def test_a_size_with_no_comparable_sales_says_so():
    at = run_app()
    widget(at.sidebar.number_input, "Size (sqft)").set_value(20_000).run()

    assert not at.exception
    assert "Not enough similar sales" in headings(at)


def test_pipeline_view_reports_every_example_deal():
    at = run_app(mode="pipeline")

    assert not at.exception
    assert at.metric[0].value == "12"  # all deals in the example CSV
    assert at.metric[3].label == "Deposits at risk"


def test_the_address_follows_the_chosen_view():
    at = run_app(mode="pipeline")  # e.g. opened from a link to the pipeline
    at.sidebar.segmented_control[0].set_value("Deal").run()

    assert not at.exception
    assert "mode" not in at.query_params  # so a refresh, or the plain link, opens the Deal view
    assert "Who pays" in headings(at)

    at.sidebar.segmented_control[0].set_value("Method").run()
    assert at.query_params["mode"] == "method"


def test_method_view_explains_the_problem_and_the_assumptions():
    at = run_app(mode="method")

    assert not at.exception
    for section in ("The problem", "How the estimate works", "Accuracy", "Assumptions", "Limitations"):
        assert section in headings(at)
