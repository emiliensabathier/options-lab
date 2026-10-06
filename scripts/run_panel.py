"""Run the surface comparison on archived sessions and write the aggregate panel.

Two sources, each fetched into ``cache/`` by its own script and never committed:

- ``hd``: HistoricalData.net's SPX/SPXW closes, July to December 2022
  (``scripts/fetch_eod_sample.py``).
- ``spy``: the SPY closes lambdaclass redistributes, 2008 to 2025, with the three-month
  bill that pins their discount (``scripts/fetch_spy_archive.py``).

Either is sampled at the first session of each day, week, month or quarter. A coarse pass
then a finer one resumes into the same file, so a quarterly panel exists early.

Each session's four fits and audits append one row per model to the source's panel CSV.
Sessions already in the panel are skipped, so an interrupted run resumes. A session whose
strikes defeat the CBOE recipe keeps its fits with the recipe left blank. Only aggregate
numbers are written: neither archive may be redistributed from here.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from olab.eod import load_eod_day
from olab.errors import CalibrationError, DataError
from olab.panel import sample_sessions, surface_rows
from olab.pipeline import surface_from_snapshot
from olab.spy import bill_rate, load_spy_day

ROOT = Path(__file__).resolve().parents[1]
VIX = ROOT / "data" / "raw" / "vix_spx_daily.csv"
HD_CACHE = ROOT / "cache" / "eod_2022h2"
SPY_CACHE = ROOT / "cache" / "spy"
PANELS = {
    "hd": ROOT / "data" / "panel" / "surface_panel_2022h2.csv",
    "spy": ROOT / "data" / "panel" / "surface_panel_spy.csv",
}


def hd_sessions(args) -> dict[str, object]:
    paths = {path.name.split("_")[0]: path for path in HD_CACHE.glob("*_options.csv")}
    if not paths:
        raise SystemExit(f"no *_options.csv in {HD_CACHE}; run scripts/fetch_eod_sample.py")
    days = sample_sessions(paths, args.period, args.first, args.last)
    return {day: (lambda vix, p=paths[day]: load_eod_day(p, vix_close=vix)) for day in days}


def spy_sessions(args) -> dict[str, object]:
    options, underlying = SPY_CACHE / "SPY_options.parquet", SPY_CACHE / "SPY_underlying.parquet"
    bills_path = SPY_CACHE / "DTB3.csv"
    if not (options.exists() and bills_path.exists()):
        raise SystemExit(f"no archive or bills in {SPY_CACHE}; run scripts/fetch_spy_archive.py")
    bills = pd.read_csv(bills_path, index_col=0, na_values=".").iloc[:, 0]
    bills = bills.set_axis(pd.to_datetime(bills.index).strftime("%Y-%m-%d"))
    dates = pq.read_table(underlying, columns=["date"]).column("date").to_pylist()
    days = sample_sessions(dates, args.period, args.first, args.last)
    return {
        day: (
            lambda vix, day=day: load_spy_day(
                options, underlying, day, vix_close=vix, rate=bill_rate(bills, day)
            )
        )
        for day in days
    }


SOURCES = {"hd": hd_sessions, "spy": spy_sessions}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", choices=sorted(SOURCES), default="hd")
    parser.add_argument("--period", choices=("D", "W", "M", "Q"), default="M",
                        help="first session of each day, week, month or quarter")
    parser.add_argument("--first", default="2008-01-01")
    parser.add_argument("--last", default="2025-12-31")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    output = args.output or PANELS[args.source]

    sessions = SOURCES[args.source](args)
    vix = pd.read_csv(VIX, index_col="date")["vix"]
    done = set(pd.read_csv(output)["date"]) if output.exists() else set()
    output.parent.mkdir(parents=True, exist_ok=True)

    for date, load in sessions.items():
        if date in done:
            continue
        started = time.monotonic()
        published = float(vix[date]) if date in vix.index else None
        try:
            result = surface_from_snapshot(load(published), require_recipe=False)
        except (CalibrationError, DataError) as error:
            print(f"{date}: skipped, {error}", flush=True)
            continue
        rows = pd.DataFrame(surface_rows(result, published)).assign(source=args.source)
        rows.to_csv(output, mode="a", header=not output.exists(), index=False)
        print(f"{date}: {len(result.quotes.table)} quotes, {time.monotonic() - started:.0f}s",
              flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
