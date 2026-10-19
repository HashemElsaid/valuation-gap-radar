"""Smoke tests for the Streamlit app: each main screen renders without errors.

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


def test_one_deal_page_shows_a_verdict():
    at = run_app()

    assert not at.exception
    assert "We estimate the bank will value it at about" in page_text(at)
    assert len(at.tabs) == 3


def test_choosing_a_building_uses_its_sales():
    at = run_app()
    building = widget(at.sidebar.selectbox, "Building (optional)")
    building.set_value(building.options[1]).run()  # the busiest building in the area
    chosen = widget(at.sidebar.selectbox, "Building (optional)").value

    assert not at.exception
    assert any(f"sales in {chosen}" in c.value for c in at.caption)  # comps came from that building


def test_a_size_with_no_comparable_sales_says_so():
    at = run_app()
    widget(at.sidebar.number_input, "Size (sqft)").set_value(20_000).run()

    assert not at.exception
    assert "Not enough similar sales" in page_text(at)


def test_pipeline_mode_reports_every_example_deal():
    at = run_app(mode="pipeline")

    assert not at.exception
    assert at.metric[0].value == "12"  # Deals checked
