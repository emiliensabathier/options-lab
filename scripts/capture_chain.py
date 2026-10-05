"""Capture one intraday snapshot of the SPX option chain, with the index levels it is read against.

Run during US market hours: outside them Yahoo serves zero bids and the snapshot is unusable.
The output is the frozen input the surface half of the study is computed from.
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
MAX_DAYS = 400
LEVELS = ("^SPX", "^VIX", "^VIX9D", "^VIX3M")


def _level(symbol: str) -> dict:
    info = yf.Ticker(symbol).fast_info
    return {"symbol": symbol, "last": float(info["last_price"])}


def main() -> int:
    started = datetime.now(UTC)
    ticker = yf.Ticker("^SPX")
    frames = []
    for expiry in ticker.options:
        days = (pd.Timestamp(expiry) - pd.Timestamp(started.date())).days
        if days > MAX_DAYS:
            break
        chain = ticker.option_chain(expiry)
        for kind, frame in (("C", chain.calls), ("P", chain.puts)):
            frames.append(frame.assign(expiry=expiry, kind=kind))
    quotes = pd.concat(frames, ignore_index=True)
    finished = datetime.now(UTC)
    levels = [_level(s) for s in LEVELS]
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    quotes.to_csv(OUT / f"spx_chain_{stamp}.csv", index=False)
    meta = {
        "captured_from_utc": started.isoformat(),
        "captured_to_utc": finished.isoformat(),
        "source": "Yahoo Finance via yfinance, 15-minute delayed quotes",
        "levels": levels,
        "rows": len(quotes),
    }
    (OUT / f"spx_chain_{stamp}.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
