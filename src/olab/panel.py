"""The surface comparison repeated across sessions, reduced to aggregate numbers.

One snapshot gives one afternoon's counts. Running the same four fits and audits on every
session of an archive turns each number into a distribution, and asks whether the ranking
the snapshot shows (free SVI closest to the quotes, eSSVI ahead of SSVI) is a property of
the models or of the afternoon. Only these aggregates are kept: the archived quotes
themselves are licensed for use, not redistribution.
"""

from __future__ import annotations

import pandas as pd

from olab.pipeline import SurfaceOutput
from olab.snapshot import NEW_YORK

# Increasing RMSE, as in the 2026-10-05 snapshot.
RANKING = ("SVI per slice", "SVI + penalties", "eSSVI", "SSVI")
VIOLATIONS = ("butterfly_quoted", "butterfly_extrapolated", "calendar_quoted",
              "calendar_extrapolated")
LOW, HIGH = 0.1, 0.9


def surface_rows(output: SurfaceOutput, published_vix: float | None) -> list[dict]:
    """One row per model: fit, arbitrage left, thirty-day vol, and the session's VIX."""
    session = {
        "date": str(output.snapshot.as_of.tz_convert(NEW_YORK).date()),
        "quotes": len(output.quotes.table),
        "expiries": len(output.quotes.forwards),
        "cboe_vix": output.cboe["vix"],
        "published_vix": published_vix,
    }
    return [
        {
            "date": session["date"],
            "model": name,
            "rmse_vol_points": model.errors["rmse_vol_points"],
            "max_abs_vol_points": model.errors["max_abs_vol_points"],
            "share_inside_spread": model.errors["share_inside_spread"],
            **{key: model.violations[key] for key in VIOLATIONS},
            "replicated_vix": model.replicated_vix,
            **{key: session[key] for key in ("cboe_vix", "published_vix", "quotes", "expiries")},
        }
        for name, model in output.models.items()
    ]


def ranking_holds(panel: pd.DataFrame) -> pd.Series:
    """Per session, whether RMSE increases strictly in the snapshot's order."""
    rmse = panel.pivot(index="date", columns="model", values="rmse_vol_points")[list(RANKING)]
    return (rmse.diff(axis=1).iloc[:, 1:] > 0).all(axis=1)


def panel_summary(panel: pd.DataFrame) -> dict:
    """Distributions per model, ranking stability, and the CBOE recipe against the index."""
    grouped = panel.groupby("model")
    models = pd.DataFrame({
        "rmse_median": grouped["rmse_vol_points"].median(),
        "rmse_low": grouped["rmse_vol_points"].quantile(LOW),
        "rmse_high": grouped["rmse_vol_points"].quantile(HIGH),
        "inside_median": grouped["share_inside_spread"].median(),
        "sessions_with_quoted_butterfly": (panel["butterfly_quoted"] > 0)
        .groupby(panel["model"]).sum(),
        "sessions_with_quoted_calendar": (panel["calendar_quoted"] > 0)
        .groupby(panel["model"]).sum(),
        "wings_median": (panel["butterfly_extrapolated"] + panel["calendar_extrapolated"])
        .groupby(panel["model"]).median(),
        "replicated_minus_published_median": (panel["replicated_vix"] - panel["published_vix"])
        .groupby(panel["model"]).median(),
    }).loc[list(RANKING)]
    sessions = panel.drop_duplicates("date")
    gap = sessions["cboe_vix"] - sessions["published_vix"]
    return {
        "sessions": len(sessions),
        "first": sessions["date"].min(),
        "last": sessions["date"].max(),
        "published_vix_range": (sessions["published_vix"].min(), sessions["published_vix"].max()),
        "quotes_median": float(sessions["quotes"].median()),
        "expiries_median": float(sessions["expiries"].median()),
        "ranking_share": float(ranking_holds(panel).mean()),
        "models": models,
        "recipe_gap_median": float(gap.median()),
        "recipe_gap_low": float(gap.quantile(LOW)),
        "recipe_gap_high": float(gap.quantile(HIGH)),
    }
