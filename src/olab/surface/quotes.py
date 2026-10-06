"""From raw quotes to out-of-the-money implied volatilities, with every refusal counted.

Each quote either becomes an implied volatility or is set aside under a named reason, and
the ledger of reasons is published next to the fit. A filter that cannot be audited is
indistinguishable from a fit tuned by deleting the points it misses.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from olab.black import implied_vol
from olab.errors import DataError
from olab.surface.forwards import Forward, implied_forward

MIN_MATURITY = 7.0 / 365.0  # inside a week the smile is dominated by event and gamma noise
MAX_RELATIVE_SPREAD = 0.5  # (ask - bid) / mid
MAX_ABS_LOG_MONEYNESS = 0.6
# Yahoo leaves a contract's bid and ask as they stood at its last trade. In this capture,
# quotes whose last trade is older than about six weeks sit tens of points off their
# neighbours (a put bid at 78 next to one at 33, five points of strike away); the count
# of executable arbitrages is flat for any cutoff between 3 and 30 days and jumps after 45.
MAX_QUOTE_AGE_DAYS = 30.0


@dataclass(frozen=True)
class SurfaceQuotes:
    """Out-of-the-money quotes in implied-volatility terms, one row per strike and expiry."""

    table: pd.DataFrame
    forwards: dict[str, Forward]
    screened: pd.DataFrame
    refused: Counter = field(default_factory=Counter)


def is_stale(quotes: pd.DataFrame, as_of: pd.Timestamp) -> pd.Series:
    """True where the last trade, and so the displayed quote, predates the cutoff."""
    traded = pd.to_datetime(quotes["lastTradeDate"], utc=True)
    age = (as_of - traded).dt.total_seconds() / 86400.0
    return ~(age <= MAX_QUOTE_AGE_DAYS)


def screen_quotes(
    quotes: pd.DataFrame, as_of: pd.Timestamp | None = None
) -> tuple[pd.DataFrame, Counter]:
    """Quote-level filters, applied before any model is involved.

    Without ``as_of`` the staleness filter is skipped, which is how the report measures
    what that one filter removes.
    """
    refused: Counter = Counter()
    reasons = [
        ("no_bid", quotes["bid"] <= 0.0),
        ("crossed", quotes["ask"] < quotes["bid"]),
    ]
    if as_of is not None:
        reasons.append(("stale_last_trade", is_stale(quotes, as_of)))
    keep = pd.Series(True, index=quotes.index)
    for reason, mask in reasons:
        hit = keep & mask
        refused[reason] += int(hit.sum())
        keep &= ~mask
    mid = 0.5 * (quotes["bid"] + quotes["ask"])
    wide = keep & ((quotes["ask"] - quotes["bid"]) > MAX_RELATIVE_SPREAD * mid)
    refused["spread_too_wide"] += int(wide.sum())
    keep &= ~wide
    return quotes.loc[keep].assign(mid=mid[keep]), refused


def _vol_row(row, fwd: Forward, refused: Counter) -> dict | None:
    is_call = row.kind == "C"
    vols = {}
    for side in ("bid", "mid", "ask"):
        price = getattr(row, side) / fwd.discount
        sigma, reason = implied_vol(price, fwd.forward, row.strike, fwd.maturity, is_call)
        if sigma is None:
            refused[f"{side}_{reason}"] += 1
            return None
        vols[side] = sigma
    return {
        "expiry": fwd.expiry,
        "T": fwd.maturity,
        "strike": row.strike,
        "kind": row.kind,
        "bid": row.bid,
        "ask": row.ask,
        "forward": fwd.forward,
        "k": float(np.log(row.strike / fwd.forward)),
        "iv_bid": vols["bid"],
        "iv": vols["mid"],
        "iv_ask": vols["ask"],
    }


def build_quotes(
    quotes: pd.DataFrame, spot: float, as_of: pd.Timestamp, rate: float | None = None
) -> SurfaceQuotes:
    """Screen, imply forwards, keep the out-of-the-money side, invert to volatilities.

    ``rate`` pins every expiry's discount, for American chains (see ``implied_forward``).
    """
    short = quotes["T"] < MIN_MATURITY
    refused: Counter = Counter({"maturity_under_7_days": int(short.sum())})
    screened, screen_refusals = screen_quotes(quotes.loc[~short], as_of)
    refused.update(screen_refusals)

    rows: list[dict] = []
    forwards: dict[str, Forward] = {}
    for expiry, group in screened.groupby("expiry", sort=True):
        fwd, reason = implied_forward(group, spot, rate)
        if fwd is None:
            refused[f"expiry_{reason}"] += len(group)
            continue
        forwards[expiry] = fwd
        otm = np.where(group["strike"] >= fwd.forward, "C", "P")
        side = group.loc[group["kind"] == otm]
        refused["in_the_money_side"] += len(group) - len(side)
        far = np.abs(np.log(side["strike"] / fwd.forward)) > MAX_ABS_LOG_MONEYNESS
        refused["beyond_moneyness_range"] += int(far.sum())
        for row in side.loc[~far].itertuples(index=False):
            vol = _vol_row(row, fwd, refused)
            if vol is not None:
                rows.append(vol)

    if not rows:
        raise DataError(f"no quote survived screening; refusals: {dict(+refused)}")
    table = pd.DataFrame(rows).sort_values(["T", "strike"]).reset_index(drop=True)
    return SurfaceQuotes(table=table, forwards=forwards, screened=screened, refused=+refused)
