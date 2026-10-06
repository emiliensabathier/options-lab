"""End-of-day SPY chains from the archive lambdaclass redistributes, read as snapshots.

The file holds every session from 2008 in one parquet table; a session is read with a
filter on ``date``, never the whole table. Three conventions differ from an SPX capture:

- SPY options are American and settle into shares at the 16:00 close of expiry day. Only
  the out-of-the-money side enters the fits, where early exercise is worth little, and
  maturities stop at one year, beyond which the parity forward near the money would carry
  the early-exercise premium of the in-the-money leg. Dividends sit inside that forward.
- A side with no quote is a zero. A zero bid stays (the screen refuses it as ``no_bid`` and
  the CBOE recipe's truncation rule reads it); a zero ask leaves no price, and the row goes.
- There is no last-trade date, so the thirty-day staleness rule cannot be applied: every
  quote is stamped as trading at the close.

The spot is the unadjusted SPY close from the archive's underlying table, the price the
strikes are struck against. SPY is close to a tenth of SPX, so a thirty-day variance read
from it compares with the published VIX, but the CBOE recipe on SPY is an approximation of
the index, not the index.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from olab.errors import DataError
from olab.snapshot import NEW_YORK, Snapshot, parse_symbols, year_fractions

CLOSE = "16:00"
KINDS = {"call": "C", "put": "P"}
COLUMNS = ["contract_id", "expiration", "strike", "type", "bid", "ask"]
MAX_MATURITY = 1.0


def session_close(underlying: Path, day: str) -> float:
    """The unadjusted SPY close of one session."""
    closes = pq.read_table(underlying, columns=["close"], filters=[("date", "==", day)])
    if closes.num_rows != 1:
        raise DataError(f"{day}: {closes.num_rows} SPY closes in {Path(underlying).name}")
    return float(closes.column("close")[0].as_py())


def load_spy_day(options: Path, underlying: Path, day: str,
                 vix_close: float | None = None) -> Snapshot:
    """One session of the archive, reduced to the columns and conventions the pipeline reads."""
    raw = pq.read_table(options, columns=COLUMNS,
                        filters=[("date", "==", pd.Timestamp(day))]).to_pandas()
    if raw.empty:
        raise DataError(f"{day}: no SPY quotes in {Path(options).name}")
    spot = session_close(underlying, day)

    as_of = pd.Timestamp(f"{day} {CLOSE}").tz_localize(NEW_YORK).tz_convert("UTC")
    priced = raw.loc[raw["ask"] > 0]
    quotes = pd.DataFrame({
        "contractSymbol": priced["contract_id"],
        "strike": priced["strike"].astype(float),
        "bid": priced["bid"].fillna(0.0).astype(float),
        "ask": priced["ask"].astype(float),
        "expiry": pd.to_datetime(priced["expiration"]).dt.strftime("%Y-%m-%d"),
        "kind": priced["type"].map(KINDS),
        "lastTradeDate": as_of,
    }).reset_index(drop=True)
    quotes = parse_symbols(quotes)
    quotes = quotes.assign(T=year_fractions(quotes, as_of))
    quotes = quotes.loc[quotes["T"] <= MAX_MATURITY].reset_index(drop=True)
    levels = {"SPY": spot} | ({} if vix_close is None else {"^VIX": float(vix_close)})
    return Snapshot(quotes=quotes, as_of=as_of, spot=spot, levels=levels)
