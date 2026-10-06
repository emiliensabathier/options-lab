"""End-of-day SPX chains from HistoricalData.net's archive, read as snapshots.

The archive's layout differs from a Yahoo capture in three ways that matter here:

- A side with no quote is blank, never zero. A blank bid is read as a zero bid, which is
  what the screen refuses as ``no_bid`` and what the CBOE recipe's truncation rule reads;
  a blank ask leaves no price to trade at, and the row is dropped.
- ``last_trade_date`` is a date. It is placed at the close of that day, and a blank one
  (not seen trading in the archive) is treated as stale.
- ``quote_time`` is empty before 2026-08, so the quotes are the ones standing at the close
  and ``as_of`` is 16:00 New York on ``quote_date``, the instant of ``underlying_close``.
  Index options quote until 16:15, so a quote can be up to fifteen minutes younger.

The contract symbol carries the root (``SPX`` or ``SPXW``); the ``underlying`` column does
not always, so roots are read from the symbol as for a capture.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from olab.errors import DataError
from olab.snapshot import NEW_YORK, Snapshot, parse_symbols, select_roots, year_fractions

CLOSE = "16:00"
KINDS = {"call": "C", "put": "P"}
REQUIRED = ("contract", "expiration", "type", "strike", "quote_date", "bid", "ask",
            "last_trade_date", "underlying_close")


def _at_close(dates: pd.Series) -> pd.Series:
    stamps = pd.to_datetime(dates + f" {CLOSE}", errors="coerce")
    return stamps.dt.tz_localize(NEW_YORK).dt.tz_convert("UTC")


def load_eod_day(path: Path, vix_close: float | None = None) -> Snapshot:
    """One session's file, reduced to the columns and conventions the pipeline reads."""
    raw = pd.read_csv(path, dtype={"contract": str, "expiration": str, "quote_date": str,
                                   "last_trade_date": str})
    missing = [c for c in REQUIRED if c not in raw.columns]
    if missing:
        raise DataError(f"{path.name} lacks columns {missing}")
    dates = raw["quote_date"].unique()
    if len(dates) != 1:
        raise DataError(f"{path.name} mixes quote dates {sorted(dates)}")
    closes = raw["underlying_close"].dropna().unique()
    if len(closes) != 1:
        raise DataError(f"{path.name} has no single index close: {closes}")

    priced = raw.loc[raw["ask"].notna()]
    quotes = pd.DataFrame({
        "contractSymbol": priced["contract"],
        "strike": priced["strike"].astype(float),
        "bid": priced["bid"].fillna(0.0).astype(float),
        "ask": priced["ask"].astype(float),
        "expiry": priced["expiration"],
        "kind": priced["type"].map(KINDS),
        "lastTradeDate": _at_close(priced["last_trade_date"]),
    }).reset_index(drop=True)

    as_of = pd.Timestamp(f"{dates[0]} {CLOSE}").tz_localize(NEW_YORK).tz_convert("UTC")
    quotes = select_roots(parse_symbols(quotes))
    quotes = quotes.assign(T=year_fractions(quotes, as_of))
    spot = float(closes[0])
    levels = {"^SPX": spot} | ({} if vix_close is None else {"^VIX": float(vix_close)})
    return Snapshot(quotes=quotes, as_of=as_of, spot=spot, levels=levels)
