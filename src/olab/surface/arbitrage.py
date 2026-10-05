"""Static arbitrage, checked twice: in the raw chain, and in a fitted surface.

In the chain, a violation only counts if it can be traded: a call spread or butterfly that
earns money when every leg is bought at the ask and sold at the bid. A mid-price violation
that the spread absorbs is noise, not arbitrage.

In a fitted surface the checks are the standard ones on total variance ``w(k)``:

- butterfly: Durrleman's condition ``g(k) >= 0``, which is the risk-neutral density being
  non-negative (Gatheral and Jacquier, 2014);
- calendar: ``w(k, T)`` non-decreasing in ``T`` at every ``k``.

Derivatives are taken by central differences so the same check runs on any slice, SVI or
SSVI, without trusting a closed form that could share a bug with the model it audits.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import numpy as np
import pandas as pd

TOLERANCE = 1e-9
STEP = 1e-4
K_GRID = np.linspace(-0.6, 0.6, 1201)

Slice = Callable[[np.ndarray], np.ndarray]


def durrleman_g(total_variance: Slice, k: np.ndarray = K_GRID) -> np.ndarray:
    """Durrleman's ``g(k)``; negative wherever the implied density is negative."""
    w = total_variance(k)
    w_up, w_dn = total_variance(k + STEP), total_variance(k - STEP)
    d1 = (w_up - w_dn) / (2 * STEP)
    d2 = (w_up - 2 * w + w_dn) / STEP**2
    return (1 - k * d1 / (2 * w)) ** 2 - d1**2 / 4 * (1 / w + 0.25) + d2 / 2


def butterfly_violations(total_variance: Slice, k: np.ndarray = K_GRID) -> int:
    """Grid points where the slice implies a negative density, or a non-positive variance."""
    w = total_variance(k)
    if (w <= 0).any():
        return int((w <= 0).sum())
    return int((durrleman_g(total_variance, k) < -TOLERANCE).sum())


def calendar_violations(slices: Sequence[Slice], k: np.ndarray = K_GRID) -> int:
    """Grid points where a later slice carries less total variance than an earlier one."""
    count = 0
    for earlier, later in zip(slices[:-1], slices[1:], strict=True):
        count += int((later(k) < earlier(k) - TOLERANCE).sum())
    return count


def between_pillars(surface, maturities: np.ndarray, k: np.ndarray = K_GRID) -> dict[str, int]:
    """Butterfly and calendar violations on maturities between the fitted expiries.

    A surface audited only at its pillars can still cross itself in between; this reads the
    interpolated slices the replication and any off-pillar price would use.
    """
    slices = [surface.slice(float(t)) for t in maturities]
    return {
        "maturities": len(slices),
        "butterfly": sum(butterfly_violations(curve, k) for curve in slices),
        "calendar": calendar_violations(slices, k),
    }


def _tradable_in_one_type(frame: pd.DataFrame, is_call: bool) -> dict[str, int]:
    frame = frame.sort_values("strike")
    strikes = frame["strike"].to_numpy(dtype=float)
    bid, ask = frame["bid"].to_numpy(dtype=float), frame["ask"].to_numpy(dtype=float)
    # A call is worth more at a lower strike, a put at a higher one. A vertical is an
    # arbitrage when the leg that must be worth more can be bought below the other's bid.
    if is_call:
        vertical = ask[:-1] < bid[1:]
    else:
        vertical = ask[1:] < bid[:-1]
    k1, k2, k3 = strikes[:-2], strikes[1:-1], strikes[2:]
    weight = (k3 - k2) / (k3 - k1)
    butterfly = weight * ask[:-2] + (1 - weight) * ask[2:] < bid[1:-1]
    return {"vertical": int(vertical.sum()), "butterfly": int(butterfly.sum())}


def tradable_chain_arbitrage(quotes: pd.DataFrame) -> dict[str, int]:
    """Count executable vertical and butterfly arbitrages in screened quotes, per type."""
    totals = {"vertical": 0, "butterfly": 0, "checked_expiries": 0}
    for _, group in quotes.groupby("expiry"):
        totals["checked_expiries"] += 1
        for kind, is_call in (("C", True), ("P", False)):
            side = group.loc[group["kind"] == kind]
            if len(side) < 3:
                continue
            found = _tradable_in_one_type(side, is_call)
            totals["vertical"] += found["vertical"]
            totals["butterfly"] += found["butterfly"]
    return totals


def split_violations(
    slices: Sequence[Slice], ranges: Sequence[tuple[float, float]], k: np.ndarray = K_GRID
) -> dict[str, int]:
    """Butterfly and calendar violations, inside the quoted strikes and beyond them.

    ``ranges`` gives each slice's quoted log-moneyness span; a calendar pair is "quoted"
    where both slices have quotes. The split matters: a slice can be clean wherever the
    market prices it and still imply a negative density in the wing it extrapolates, and a
    replication integral or a far-strike quote reads exactly that wing.
    """
    counts = dict.fromkeys(
        ("butterfly_quoted", "butterfly_extrapolated", "calendar_quoted", "calendar_extrapolated"),
        0,
    )
    for curve, (lo, hi) in zip(slices, ranges, strict=True):
        w = curve(k)
        bad = (w <= 0) | (durrleman_g(curve, k) < -TOLERANCE)
        inside = (k >= lo) & (k <= hi)
        counts["butterfly_quoted"] += int((bad & inside).sum())
        counts["butterfly_extrapolated"] += int((bad & ~inside).sum())
    pairs = zip(slices[:-1], slices[1:], ranges[:-1], ranges[1:], strict=True)
    for earlier, later, (lo0, hi0), (lo1, hi1) in pairs:
        bad = later(k) < earlier(k) - TOLERANCE
        inside = (k >= max(lo0, lo1)) & (k <= min(hi0, hi1))
        counts["calendar_quoted"] += int((bad & inside).sum())
        counts["calendar_extrapolated"] += int((bad & ~inside).sum())
    return counts
