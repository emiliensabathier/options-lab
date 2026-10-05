"""VIX against the variance the S&P 500 then realized, 1990 onward.

The VIX is, by construction, the thirty-day variance-swap rate on the index: the square of
it is the fixed leg a variance buyer pays. Holding the swap to expiry pays

    realized variance - VIX^2

to the buyer, so the seller's average take is the variance risk premium, measured directly,
with no option model in between.

Conventions, each a choice:

- **Realized variance** is the sum of squared daily close-to-close log returns over the next
  21 trading days, annualised by 252/21, with no mean subtracted: the variance-swap payoff
  convention, not the sample variance.
- **Non-overlapping windows.** Consecutive daily observations share 20 of their 21 returns,
  so treating them as independent overstates the evidence about twenty-fold. The headline
  statistics use one window every 21 trading days, and every one of the 21 possible
  starting offsets is run to show how much the answer depends on that arbitrary phase.
- **Profit and loss per unit of vega notional**: ``(K^2 - RV) / (2K)``, in volatility
  points. It reads as "how many vol points the seller earned", and it is the scaling under
  which a one-point miss costs the same at every strike level.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from olab.errors import DataError

WINDOW = 21
ANNUALISATION = 252
CAP_MULTIPLE = 2.5  # listed variance swaps cap realized volatility at 2.5x the strike


def load_history(csv: Path, last_complete: pd.Timestamp | None = None) -> pd.DataFrame:
    """Read the frozen VIX and S&P 500 closes.

    Rows where the index has no close are exchange holidays on which Yahoo still prints a
    VIX value; they are dropped, and they are the only rows allowed to go. A row dated on or
    after ``last_complete`` is an unfinished session and is dropped too.
    """
    frame = pd.read_csv(csv, index_col="date", parse_dates=["date"])
    if not {"vix", "spx"} <= set(frame.columns):
        raise DataError("history must carry vix and spx columns")
    if frame["vix"].isna().any():
        raise DataError("missing VIX closes; refusing to fill")
    frame = frame.dropna(subset=["spx"])
    if last_complete is not None:
        frame = frame.loc[frame.index < last_complete.normalize()]
    if not frame.index.is_monotonic_increasing or frame.index.has_duplicates:
        raise DataError("history dates are unsorted or duplicated")
    return frame


def forward_realized_variance(spx: pd.Series, window: int = WINDOW) -> pd.Series:
    """Realized variance over the ``window`` trading days after each date, annualised.

    The value dated ``t`` uses returns from ``t+1`` to ``t+window`` only: it is what a swap
    struck at the close of ``t`` settles on. The last ``window`` dates have no full window
    and are dropped rather than padded.
    """
    squared = np.log(spx).diff() ** 2
    forward_sum = squared[::-1].rolling(window).sum()[::-1].shift(-1)
    return (forward_sum * ANNUALISATION / window).dropna()


def swap_outcomes(history: pd.DataFrame) -> pd.DataFrame:
    """Every daily-struck thirty-day swap: strike, realized, and the seller's profit."""
    realized = forward_realized_variance(history["spx"])
    strike = (history["vix"] / 100.0).reindex(realized.index)
    capped = np.minimum(realized, (CAP_MULTIPLE * strike) ** 2)
    return pd.DataFrame(
        {
            "implied_vol": strike,
            "realized_vol": np.sqrt(realized),
            "variance_premium": strike**2 - realized,
            "seller_pnl_vol_points": 100 * (strike**2 - realized) / (2 * strike),
            "capped_seller_pnl_vol_points": 100 * (strike**2 - capped) / (2 * strike),
        }
    )


def non_overlapping(outcomes: pd.DataFrame, offset: int = 0) -> pd.DataFrame:
    """One swap every ``WINDOW`` trading days, starting ``offset`` days in."""
    if not 0 <= offset < WINDOW:
        raise ValueError(f"offset must lie in [0, {WINDOW})")
    return outcomes.iloc[offset::WINDOW]


@dataclass(frozen=True)
class Regression:
    """Mincer-Zarnowitz: realized = alpha + beta * implied, with White standard errors."""

    alpha: float
    beta: float
    alpha_se: float
    beta_se: float
    r_squared: float
    observations: int

    @property
    def t_beta_equals_one(self) -> float:
        return (self.beta - 1.0) / self.beta_se


def mincer_zarnowitz(implied: pd.Series, realized: pd.Series) -> Regression:
    """Is the implied forecast unbiased? Unbiased means alpha = 0 and beta = 1.

    White (HC0) errors, because realized variance is far more dispersed when implied is
    high; homoskedastic errors would understate the uncertainty exactly where it matters.
    """
    x = np.column_stack([np.ones(len(implied)), implied.to_numpy()])
    y = realized.to_numpy()
    coef, *_ = np.linalg.lstsq(x, y, rcond=None)
    resid = y - x @ coef
    bread = np.linalg.inv(x.T @ x)
    meat = x.T @ (x * resid[:, None] ** 2)
    cov = bread @ meat @ bread
    r2 = 1.0 - resid.var() / y.var()
    return Regression(
        alpha=float(coef[0]),
        beta=float(coef[1]),
        alpha_se=float(np.sqrt(cov[0, 0])),
        beta_se=float(np.sqrt(cov[1, 1])),
        r_squared=float(r2),
        observations=len(y),
    )


def summarise(sample: pd.DataFrame) -> dict[str, float]:
    """Headline statistics of one non-overlapping sample."""
    pnl = sample["seller_pnl_vol_points"]
    return {
        "windows": int(len(sample)),
        "mean_implied_vol": float(sample["implied_vol"].mean()),
        "mean_realized_vol": float(sample["realized_vol"].mean()),
        "share_implied_above_realized": float(
            (sample["implied_vol"] > sample["realized_vol"]).mean()
        ),
        "mean_seller_pnl": float(pnl.mean()),
        "median_seller_pnl": float(pnl.median()),
        "worst_seller_pnl": float(pnl.min()),
        "mean_capped_seller_pnl": float(sample["capped_seller_pnl_vol_points"].mean()),
        "annualised_sharpe": float(pnl.mean() / pnl.std(ddof=1) * np.sqrt(ANNUALISATION / WINDOW)),
        "skewness": float(pnl.skew()),
    }


def offset_sensitivity(outcomes: pd.DataFrame) -> pd.DataFrame:
    """The headline statistics for each of the 21 possible sampling phases."""
    rows = {offset: summarise(non_overlapping(outcomes, offset)) for offset in range(WINDOW)}
    return pd.DataFrame(rows).T


def by_vix_regime(sample: pd.DataFrame, edges: tuple[float, ...] = (0.15, 0.25)) -> pd.DataFrame:
    """Seller outcomes conditional on the VIX level at the strike date."""
    bins = [-np.inf, *edges, np.inf]
    labels = [f"VIX < {edges[0]*100:.0f}"]
    labels += [f"{lo*100:.0f}-{hi*100:.0f}" for lo, hi in zip(edges[:-1], edges[1:], strict=True)]
    labels += [f"VIX >= {edges[-1]*100:.0f}"]
    regime = pd.cut(sample["implied_vol"], bins=bins, labels=labels, right=False)
    grouped = sample.groupby(regime, observed=False)["seller_pnl_vol_points"]
    return pd.DataFrame(
        {
            "windows": grouped.size(),
            "mean_pnl": grouped.mean(),
            "worst_pnl": grouped.min(),
            "share_positive": grouped.apply(lambda s: float((s > 0).mean())),
        }
    )
