"""The surface comparison repeated across sessions, reduced to aggregate numbers.

One snapshot gives one afternoon's counts. Running the same four fits and audits on every
session of an archive turns each number into a distribution, and asks whether the ranking
the snapshot shows (free SVI closest to the quotes, eSSVI ahead of SSVI) is a property of
the models or of the afternoon. Only these aggregates are kept: the archived quotes
themselves are licensed for use, not redistribution.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from olab.pipeline import SurfaceOutput
from olab.snapshot import NEW_YORK

# Increasing RMSE, as in the 2026-10-05 snapshot.
RANKING = ("SVI per slice", "SVI + penalties", "eSSVI", "SSVI")
VIOLATIONS = ("butterfly_quoted", "butterfly_extrapolated", "calendar_quoted",
              "calendar_extrapolated")
LOW, HIGH = 0.1, 0.9
REGIME_EDGES = (15.0, 25.0)  # VIX points, the premium study's regimes


def surface_rows(output: SurfaceOutput, published_vix: float | None) -> list[dict]:
    """One row per model: fit, arbitrage left, thirty-day vol, and the session's VIX."""
    session = {
        "date": str(output.snapshot.as_of.tz_convert(NEW_YORK).date()),
        "quotes": len(output.quotes.table),
        "expiries": len(output.quotes.forwards),
        "cboe_vix": float("nan") if output.cboe is None else output.cboe["vix"],
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
        "regimes": breakdown(panel, vix_regime(panel)),
        "years": breakdown(panel, panel["date"].str[:4]),
    }


def sample_sessions(dates, period: str, first: str, last: str) -> list[str]:
    """First trading session of each ``period`` ("M", "W") within ``[first, last]``."""
    stamps = pd.Series(pd.to_datetime(sorted(set(dates))))
    stamps = stamps.loc[stamps.between(pd.Timestamp(first), pd.Timestamp(last))]
    firsts = stamps.groupby(stamps.dt.to_period(period)).min()
    return [str(stamp.date()) for stamp in firsts]


def vix_regime(panel: pd.DataFrame, edges: tuple[float, ...] = REGIME_EDGES) -> pd.Series:
    """The published VIX of each row's session, binned as in the premium study."""
    labels = [f"VIX < {edges[0]:.0f}"]
    labels += [f"{lo:.0f}-{hi:.0f}" for lo, hi in zip(edges[:-1], edges[1:], strict=True)]
    labels += [f"VIX >= {edges[-1]:.0f}"]
    bins = [-np.inf, *edges, np.inf]
    return pd.cut(panel["published_vix"], bins=bins, labels=labels, right=False)


def breakdown(panel: pd.DataFrame, key: pd.Series) -> pd.DataFrame:
    """Per group of sessions: count, ranking stability, median RMSE and quoted arbitrage per
    model, and the median gap between the CBOE recipe and the published index."""
    frame = panel.assign(group=key.astype(str).to_numpy(),
                         quoted=panel["butterfly_quoted"] + panel["calendar_quoted"])
    groups = frame.drop_duplicates("date").set_index("date")["group"]
    held = ranking_holds(frame).groupby(groups).mean()
    rmse = frame.pivot_table(index="group", columns="model", values="rmse_vol_points",
                             aggfunc="median")[list(RANKING)]
    quoted = frame.pivot_table(index="group", columns="model", values="quoted",
                               aggfunc="median")[list(RANKING)].add_prefix("quoted_")
    sessions = frame.drop_duplicates("date")
    gap = (sessions["cboe_vix"] - sessions["published_vix"]).groupby(sessions["group"])
    table = pd.concat([
        sessions.groupby("group").size().rename("sessions"),
        held.rename("ranking_share"), rmse, quoted, gap.median().rename("recipe_gap"),
    ], axis=1)
    if isinstance(key.dtype, pd.CategoricalDtype):  # regimes in VIX order, not alphabetical
        table = table.reindex([c for c in key.cat.categories if c in table.index])
    return table
