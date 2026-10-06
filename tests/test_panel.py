import math
from dataclasses import replace

import pandas as pd
import pytest

from olab import pipeline
from olab.errors import DataError
from olab.panel import (
    RANKING,
    breakdown,
    panel_summary,
    ranking_holds,
    sample_sessions,
    surface_rows,
    vix_regime,
)


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
    assert summary["pairwise"][("eSSVI", "SSVI")] == pytest.approx(2 / 3)
    assert summary["pairwise"][("SVI per slice", "SVI + penalties")] == pytest.approx(1.0)


def _fails(*_):
    raise DataError("strike 3825.0 lacks a call or a put; cannot centre the strip")


def test_a_failed_recipe_costs_the_panel_one_number_not_the_session(monkeypatch, surface_output):
    monkeypatch.setattr(pipeline, "cboe_vix", _fails)

    assert pipeline.recipe(surface_output.snapshot, {}, required=False) is None
    with pytest.raises(DataError):
        pipeline.recipe(surface_output.snapshot, {}, required=True)
    rows = surface_rows(replace(surface_output, cboe=None), published_vix=15.57)
    assert all(math.isnan(r["cboe_vix"]) for r in rows)


def test_samples_the_first_session_of_each_period_inside_the_window():
    dates = ["2008-01-02", "2008-01-03", "2008-02-01", "2008-02-04", "2008-02-11", "2025-12-12"]

    monthly = sample_sessions(dates, "M", first="2008-01-01", last="2008-12-31")
    weekly = sample_sessions(dates, "W", first="2008-01-01", last="2008-12-31")

    assert monthly == ["2008-01-02", "2008-02-01"]
    assert weekly == ["2008-01-02", "2008-02-01", "2008-02-04", "2008-02-11"]


def test_breaks_the_panel_down_by_vix_regime_and_by_year():
    panel = _panel([(0.1, 0.5, 1.8, 2.0), (0.3, 0.7, 2.2, 2.0), (0.2, 0.6, 1.9, 2.4)])
    panel["published_vix"] = panel["date"].map(
        {"2022-07-01": 12.0, "2022-07-02": 30.0, "2022-07-03": 31.0})

    regimes = breakdown(panel, vix_regime(panel))
    years = breakdown(panel, panel["date"].str[:4])

    assert list(regimes.index) == ["VIX < 15", "VIX >= 25"]
    assert regimes.loc["VIX >= 25", "sessions"] == 2
    assert regimes.loc["VIX >= 25", "ranking_share"] == pytest.approx(0.5)
    assert regimes.loc["VIX >= 25", "eSSVI"] == pytest.approx(2.05)
    assert regimes.loc["VIX < 15", "recipe_gap"] == pytest.approx(13.5)
    assert regimes.loc["VIX < 15", "quoted_SVI per slice"] == 4
    assert years.loc["2022", "sessions"] == 3
