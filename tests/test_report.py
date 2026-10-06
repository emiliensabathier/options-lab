import re

import pytest

from olab import __main__ as cli
from olab.report.build import TITLE, build_report


@pytest.fixture(scope="module")
def html(surface_output, premium_output):
    return build_report(surface_output, premium_output)


def test_every_section_is_rendered(html):
    headings = re.findall(r"<h2>(.*?)</h2>", html)
    assert len(headings) == 7
    assert any("VIX" in h for h in headings)
    assert any("variance risk premium" in h for h in headings)
    assert html.count("<svg") == 4
    assert f"<title>{TITLE}</title>" in html


def test_rendering_is_deterministic(html, surface_output, premium_output):
    assert build_report(surface_output, premium_output) == html


def test_report_loads_nothing_from_the_network(html):
    assert not re.search(r"<(script|link|img)[^>]+(src|href)=", html)


def test_model_table_lists_all_four_fits(html, surface_output):
    for name in surface_output.models:
        assert name in html


def test_cli_writes_the_report(tmp_path, monkeypatch, surface_output, premium_output):
    monkeypatch.setattr(cli, "run_surface", lambda chain, meta: surface_output)
    monkeypatch.setattr(cli, "run_premium", lambda csv, meta: premium_output)
    (tmp_path / "spx_chain_20260101T000000Z.csv").write_text("", encoding="utf-8")
    output = tmp_path / "out" / "report.html"
    cli.main(["--raw", str(tmp_path), "--output", str(output)])
    assert output.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_cli_explains_a_missing_capture(tmp_path):
    with pytest.raises(SystemExit, match="capture_chain"):
        cli.latest_chain(tmp_path)


def test_panel_sections_render_per_source_with_attribution(surface_output, premium_output):
    from olab.panel import panel_summary
    from test_panel import _panel

    summary = panel_summary(_panel([(0.1, 0.5, 1.8, 2.0), (0.3, 0.7, 2.2, 2.0)]))
    page = build_report(surface_output, premium_output, {"hd": summary, "spy": summary})

    assert "The same comparison on 2 sessions of 2022" in page
    assert 'href="https://historicaldata.net/options.html"' in page
    assert "holds in 50.0% of sessions" in page
    assert "The same comparison on 2 SPY closes, 2022–2022" in page
    assert 'href="https://github.com/lambdaclass/options_backtester"' in page
    assert page.count("VIX regime") == 2
    assert "eSSVI still crosses in time inside the quoted range on 2 of 2 sessions" in page


def test_panel_note_states_a_calendar_clean_essvi_and_why(surface_output, premium_output):
    from olab.panel import panel_summary
    from test_panel import _panel

    rows = _panel([(0.1, 0.5, 1.8, 2.0)])
    rows.loc[rows["model"] == "eSSVI", "calendar_quoted"] = 0
    page = build_report(surface_output, premium_output, {"hd": panel_summary(rows)})

    assert "eSSVI never crosses in time inside the quoted range" in page
    assert "Prop. 3.5" in page
