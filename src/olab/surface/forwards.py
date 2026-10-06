"""Forward and discount factor per expiry, read off put-call parity.

For European options ``C - P = D (F - K)``: regressing the call-minus-put mid on the strike
gives ``-D`` as the slope and ``D F`` as the intercept. Both come from the chain itself, so no
funding curve and no dividend forecast is assumed. SPX options are European and cash-settled,
which is what makes the identity exact rather than a bound.

The regression has to survive stale quotes. In this capture the in-the-money leg of many
strikes carries a bid and ask that were not refreshed for weeks (last trade in August for a
quote read in October), sitting tens of index points away from parity. One such pair moves
an OLS slope by more than the whole funding rate, so pairs are trimmed iteratively: fit,
drop every pair whose residual exceeds ``TRIM_MADS`` robust standard deviations, refit,
until nothing moves. The number of pairs dropped is reported, not hidden.

American options break the identity. An in-the-money put is worth at least its exercise
value, so above the forward the put leg sits on ``K - S`` instead of ``D (K - F)`` and the
regression slope reads that floor, not a discount: on SPY closes it gives discount factors
above one. For such a chain the caller passes a short rate, the discount is pinned to it,
and the forward is read from strikes below spot only, where the in-the-money leg is a call,
which is not exercised early short of a dividend.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import theilslopes

PARITY_BAND = 0.05  # |ln(K / S)| for a strike pair to enter the regression
MIN_PAIRS = 5
TRIM_MADS = 4.0
MIN_RESIDUAL_SCALE = 0.25  # index points; stops trimming once residuals are at tick level
MAX_TRIM_ROUNDS = 10
DISCOUNT_RANGE = (0.90, 1.0005)  # a 400-day discount factor outside this is a data fault
# with a given rate: strikes from 10% under spot up to spot, so that the thin 2008-2009 SPY
# chains, struck a dollar apart near 90, still give five pairs
BELOW_SPOT_BAND = 0.10


@dataclass(frozen=True)
class Forward:
    """What one expiry's parity regression implies."""

    expiry: str
    maturity: float
    forward: float
    discount: float
    pairs: int
    trimmed: int
    residual: float  # standard deviation of the kept residuals, index points

    @property
    def rate(self) -> float:
        """Continuously compounded rate implied by the discount factor."""
        return -np.log(self.discount) / self.maturity


def _pairs(quotes: pd.DataFrame, spot: float, band=(-PARITY_BAND, PARITY_BAND)) -> pd.DataFrame:
    mids = quotes.assign(mid=0.5 * (quotes["bid"] + quotes["ask"]))
    wide = mids.pivot_table(index="strike", columns="kind", values="mid", aggfunc="first")
    if not {"C", "P"} <= set(wide.columns):
        return pd.DataFrame(columns=["C", "P"])
    wide = wide.dropna(subset=["C", "P"])
    moneyness = np.log(wide.index.to_numpy(dtype=float) / spot)
    return wide.loc[(band[0] <= moneyness) & (moneyness <= band[1])]


def trimmed_fit(strikes: np.ndarray, spread: np.ndarray) -> tuple[float, float, np.ndarray]:
    """Line through ``(strike, C - P)`` after iterative outlier trimming.

    Returns ``(slope, intercept, kept_mask)``.
    """
    # Theil-Sen first: a least-squares start dragged by a few stale pairs can leave every
    # residual outside the band, and the trim then discards the whole expiry.
    slope, intercept, _, _ = theilslopes(spread, strikes)
    kept = np.ones(len(strikes), dtype=bool)
    for _ in range(MAX_TRIM_ROUNDS):
        residual = spread - (intercept + slope * strikes)
        mad = np.median(np.abs(residual[kept] - np.median(residual[kept])))
        scale = max(1.4826 * mad, MIN_RESIDUAL_SCALE)
        new_kept = np.abs(residual) <= TRIM_MADS * scale
        if new_kept.sum() < MIN_PAIRS:
            return float(slope), float(intercept), new_kept
        converged = (new_kept == kept).all()
        kept = new_kept
        slope, intercept = np.polyfit(strikes[kept], spread[kept], 1)
        if converged:
            break
    return float(slope), float(intercept), kept


def _pinned_forward(
    pairs: pd.DataFrame, expiry: str, maturity: float, rate: float
) -> tuple[Forward | None, str | None]:
    """Forward per pair from ``K + (C - P) / D``, trimmed around the median like the line."""
    discount = float(np.exp(-rate * maturity))
    strikes = pairs.index.to_numpy(dtype=float)
    implied = strikes + (pairs["C"] - pairs["P"]).to_numpy(dtype=float) / discount
    deviation = implied - np.median(implied)
    mad = np.median(np.abs(deviation))
    kept = np.abs(deviation) <= TRIM_MADS * max(1.4826 * mad, MIN_RESIDUAL_SCALE)
    if kept.sum() < MIN_PAIRS:
        return None, "too_few_parity_pairs"
    return (
        Forward(
            expiry=expiry,
            maturity=maturity,
            forward=float(np.mean(implied[kept])),
            discount=discount,
            pairs=int(kept.sum()),
            trimmed=int((~kept).sum()),
            residual=float(implied[kept].std(ddof=1) * discount),
        ),
        None,
    )


def implied_forward(
    quotes: pd.DataFrame, spot: float, rate: float | None = None
) -> tuple[Forward | None, str | None]:
    """Fit one expiry. Returns ``(forward, None)`` or ``(None, reason)``.

    With ``rate`` (continuously compounded) the discount is pinned to it instead of read off
    the parity line: the American-chain path described above.
    """
    expiry = str(quotes["expiry"].iloc[0])
    maturity = float(quotes["T"].iloc[0])
    if rate is not None:
        pairs = _pairs(quotes, spot, band=(-BELOW_SPOT_BAND, 0.0))
        if len(pairs) < MIN_PAIRS:
            return None, "too_few_parity_pairs"
        return _pinned_forward(pairs, expiry, maturity, rate)
    pairs = _pairs(quotes, spot)
    if len(pairs) < MIN_PAIRS:
        return None, "too_few_parity_pairs"

    strikes = pairs.index.to_numpy(dtype=float)
    spread = (pairs["C"] - pairs["P"]).to_numpy(dtype=float)
    slope, intercept, kept = trimmed_fit(strikes, spread)
    if kept.sum() < MIN_PAIRS:
        return None, "too_few_parity_pairs"
    discount = -slope
    if not DISCOUNT_RANGE[0] < discount < DISCOUNT_RANGE[1]:
        return None, "discount_out_of_range"
    residual = spread[kept] - (intercept + slope * strikes[kept])
    return (
        Forward(
            expiry=expiry,
            maturity=maturity,
            forward=intercept / discount,
            discount=discount,
            pairs=int(kept.sum()),
            trimmed=int((~kept).sum()),
            residual=float(residual.std(ddof=2)) if kept.sum() > 2 else 0.0,
        ),
        None,
    )
