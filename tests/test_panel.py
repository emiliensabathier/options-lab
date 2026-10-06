import pandas as pd
import pytest

from olab.panel import RANKING, panel_summary, ranking_holds, surface_rows


def test_one_row_per_model_carrying_fit_arbitrage_and_vix(surface_output):
    rows = surface_rows(surface_output, published_vix=15.57)

    assert [r["model"] for r in rows] == list(surface_output.models)
    first = rows[0]
    model = surface_output.models[first["model"]]
    assert first["date"] == "2026-10-05"
    assert first["rmse_vol_points"] == model.errors["rmse_vol_points"]
    assert first["butterfly_quoted"] == model.violations["butterfly_quoted"]
    assert first["replicated_vix"] == model.replicated_vix
    assert first["cboe_vix"] == surface_output.cboe["vix"]
    assert first["published_vix"] == 15.57
    assert first["expiries"] == len(surface_output.quotes.forwards)
    assert {r["quotes"] for r in rows} == {len(surface_output.quotes.table)}


def _panel(rmse_by_session):
    rows = []
    for i, rmses in enumerate(rmse_by_session):
        for model, rmse in zip(RANKING, rmses, strict=True):
            rows.append({
                "date": f"2022-07-{i + 1:02d}", "model": model, "rmse_vol_points": rmse,
                "share_inside_spread": 0.5, "butterfly_quoted": 0 if "SSVI" in model else 3,
                "butterfly_extrapolated": 10, "calendar_quoted": 1, "calendar_extrapolated": 2,
                "replicated_vix": 25.0, "cboe_vix": 25.5, "published_vix": 25.0,
                "quotes": 4000, "expiries": 30,
            })
    return pd.DataFrame(rows)


def test_ranking_holds_only_where_rmse_increases_in_the_stated_order():
    panel = _panel([(0.1, 0.5, 1.8, 2.0), (0.1, 0.5, 2.1, 2.0)])

    held = ranking_holds(panel)

    assert held.tolist() == [True, False]


def test_summary_reports_distributions_per_model_and_the_recipe_gap():
    panel = _panel([(0.1, 0.5, 1.8, 2.0), (0.3, 0.7, 2.2, 2.0), (0.2, 0.6, 1.9, 2.4)])

    summary = panel_summary(panel)

    assert summary["sessions"] == 3
    assert summary["ranking_share"] == pytest.approx(2 / 3)
    essvi = summary["models"].loc["eSSVI"]
    assert essvi["rmse_median"] == pytest.approx(1.9)
    assert essvi["sessions_with_quoted_butterfly"] == 0
    assert summary["models"].loc["SVI per slice", "sessions_with_quoted_butterfly"] == 3
    assert summary["recipe_gap_median"] == pytest.approx(0.5)
