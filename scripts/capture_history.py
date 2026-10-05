"""Capture the daily VIX and S&P 500 closes that the variance-premium half of the study replays.

The S&P 500 is the price index, not total return: the variance swap settles on index
returns, and dividends are not part of its payoff.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw"
START = "1990-01-01"
SERIES = {"vix": "^VIX", "spx": "^GSPC"}


def main() -> int:
    closes = {}
    for name, symbol in SERIES.items():
        history = yf.Ticker(symbol).history(start=START, auto_adjust=False)
        if history.empty:
            raise SystemExit(f"no history returned for {symbol}")
        series = history["Close"]
        series.index = pd.DatetimeIndex(series.index.date, name="date")
        closes[name] = series
    frame = pd.DataFrame(closes)
    frame.to_csv(OUT / "vix_spx_daily.csv", float_format="%.4f")
    meta = {
        "fetched_at_utc": datetime.now(UTC).isoformat(),
        "source": "Yahoo Finance via yfinance, daily closes, unadjusted",
        "symbols": SERIES,
        "first": str(frame.index.min().date()),
        "last": str(frame.index.max().date()),
        "rows": len(frame),
        "missing": {k: int(v) for k, v in frame.isna().sum().items()},
    }
    (OUT / "vix_spx_daily.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
