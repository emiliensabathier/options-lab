"""Thirty-day fair variance, two ways, set against the VIX the CBOE published.

1. **CBOE method on the raw chain.** The VIX white paper's discrete sum over listed
   out-of-the-money strikes, on the two expiries bracketing thirty days, truncated after two
   consecutive zero bids, then interpolated to exactly thirty days. If the pipeline reads the
   chain correctly, this lands near the published index.
2. **Continuous replication on the SSVI surface.** The same log-contract integral,
   ``sigma^2 T = 2 * integral q(k) e^(-k) dk`` with ``q`` the normalised out-of-the-money
   Black premium, evaluated on the fitted thirty-day slice over a continuum of strikes.

The two differ by construction: the listed strikes stop where bids stop, the surface does
not. The gap is what the wings beyond the last quoted strike carry under the fitted smile.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.integrate import trapezoid

from olab.black import normalised_otm_price
from olab.errors import CalibrationError, DataError

THIRTY_DAYS = 30.0 / 365.0
CBOE_WINDOW = (23.0 / 365.0, 37.0 / 365.0)
INTEGRATION_STDEVS = 25.0
INTEGRATION_POINTS = 8001


def replicated_variance(total_variance, maturity: float) -> float:
    """Annualised fair variance of a slice from the continuous log-contract integral."""
    width = INTEGRATION_STDEVS * float(np.sqrt(total_variance(np.array([0.0]))[0]))
    k = np.linspace(-width, width, INTEGRATION_POINTS)
    integrand = normalised_otm_price(k, total_variance(k)) * np.exp(-k)
    return 2.0 * trapezoid(integrand, k) / maturity


@dataclass(frozen=True)
class TermVariance:
    expiry: str
    maturity: float
    variance: float
    strikes_used: int
    lowest_strike: float
    highest_strike: float


def _otm_strip(group: pd.DataFrame, k0: float) -> pd.DataFrame:
    """Out-of-the-money strikes outward from ``k0``, stopping after two consecutive zero bids."""
    kept = []
    for kind, ascending, side in (("P", False, "<"), ("C", True, ">")):
        legs = group.loc[group["kind"] == kind].sort_values("strike", ascending=ascending)
        legs = legs.loc[legs["strike"] < k0] if side == "<" else legs.loc[legs["strike"] > k0]
        zero_run = 0
        for row in legs.itertuples(index=False):
            if row.bid <= 0:
                zero_run += 1
                if zero_run == 2:
                    break
                continue
            zero_run = 0
            kept.append({"strike": row.strike, "price": 0.5 * (row.bid + row.ask)})
    at_k0 = group.loc[group["strike"] == k0]
    if set(at_k0["kind"]) != {"C", "P"}:
        raise DataError(f"strike {k0} lacks a call or a put; cannot centre the strip")
    kept.append({"strike": k0, "price": float((0.5 * (at_k0["bid"] + at_k0["ask"])).mean())})
    return pd.DataFrame(kept).sort_values("strike").reset_index(drop=True)


def cboe_term_variance(group: pd.DataFrame, discount: float) -> TermVariance:
    """One term of the VIX formula, with ``e^(RT)`` taken as ``1 / discount`` from parity."""
    maturity = float(group["T"].iloc[0])
    mids = group.assign(mid=0.5 * (group["bid"] + group["ask"]))
    wide = mids.pivot_table(index="strike", columns="kind", values="mid", aggfunc="first")
    wide = wide.dropna()
    gap = (wide["C"] - wide["P"]).abs()
    k_star = float(gap.idxmin())
    forward = k_star + (wide.loc[k_star, "C"] - wide.loc[k_star, "P"]) / discount
    below = group.loc[group["strike"] <= forward, "strike"]
    if below.empty:
        raise DataError("no listed strike at or below the forward")
    k0 = float(below.max())

    strip = _otm_strip(group, k0)
    strikes = strip["strike"].to_numpy()
    delta_k = np.gradient(strikes) if len(strikes) > 1 else np.array([0.0])
    contribution = delta_k / strikes**2 * strip["price"].to_numpy() / discount
    variance = 2.0 / maturity * contribution.sum() - (forward / k0 - 1.0) ** 2 / maturity
    return TermVariance(
        expiry=str(group["expiry"].iloc[0]),
        maturity=maturity,
        variance=float(variance),
        strikes_used=len(strikes),
        lowest_strike=float(strikes.min()),
        highest_strike=float(strikes.max()),
    )


def _bracketing(maturities: pd.Series) -> tuple[str, str]:
    by_expiry = maturities.groupby(level=0).first()
    window = by_expiry[(by_expiry > CBOE_WINDOW[0]) & (by_expiry < CBOE_WINDOW[1])]
    near = window[window < THIRTY_DAYS]
    nxt = window[window >= THIRTY_DAYS]
    if near.empty or nxt.empty:
        raise DataError("no pair of expiries brackets thirty days inside the CBOE window")
    return str(near.idxmax()), str(nxt.idxmin())


def cboe_vix(quotes: pd.DataFrame, discounts: dict[str, float]) -> dict:
    """VIX by the CBOE recipe, from raw quotes and the parity discount factors."""
    near_e, next_e = _bracketing(quotes.set_index("expiry")["T"])
    for expiry in (near_e, next_e):
        if expiry not in discounts:
            raise CalibrationError(f"no parity discount factor for {expiry}")
    near = cboe_term_variance(quotes.loc[quotes["expiry"] == near_e], discounts[near_e])
    nxt = cboe_term_variance(quotes.loc[quotes["expiry"] == next_e], discounts[next_e])
    weight = (nxt.maturity - THIRTY_DAYS) / (nxt.maturity - near.maturity)
    blended = (
        near.maturity * near.variance * weight + nxt.maturity * nxt.variance * (1 - weight)
    ) / THIRTY_DAYS
    return {"vix": 100.0 * float(np.sqrt(blended)), "near": near, "next": nxt}
