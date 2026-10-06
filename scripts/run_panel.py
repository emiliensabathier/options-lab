"""Run the surface comparison on every archived session and write the aggregate panel.

Reads the SPX/SPXW files ``scripts/fetch_eod_sample.py`` leaves under ``cache/``, fits the
four models to each session in turn, and appends one row per model to the panel CSV.
Sessions already in the panel are skipped, so an interrupted run resumes. Only aggregate
numbers are written: the archive's licence forbids redistributing its quotes.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

from olab.eod import load_eod_day
from olab.errors import CalibrationError, DataError
from olab.panel import surface_rows
from olab.pipeline import surface_from_snapshot

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "cache" / "eod_2022h2"
PANEL = ROOT / "data" / "panel" / "surface_panel_2022h2.csv"
VIX = ROOT / "data" / "raw" / "vix_spx_daily.csv"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cache", type=Path, default=CACHE)
    parser.add_argument("--output", type=Path, default=PANEL)
    args = parser.parse_args(argv)

    days = sorted(args.cache.glob("*_options.csv"))
    if not days:
        raise SystemExit(f"no *_options.csv in {args.cache}; run scripts/fetch_eod_sample.py")
    vix = pd.read_csv(VIX, index_col="date")["vix"]
    done = set(pd.read_csv(args.output)["date"]) if args.output.exists() else set()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    for path in days:
        date = path.name.split("_")[0]
        if date in done:
            continue
        started = time.monotonic()
        published = float(vix[date]) if date in vix.index else None
        try:
            output = surface_from_snapshot(load_eod_day(path, vix_close=published))
        except (CalibrationError, DataError) as error:
            print(f"{date}: skipped, {error}", flush=True)
            continue
        rows = pd.DataFrame(surface_rows(output, published))
        rows.to_csv(args.output, mode="a", header=not args.output.exists(), index=False)
        print(f"{date}: {len(output.quotes.table)} quotes, {time.monotonic() - started:.0f}s",
              flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
