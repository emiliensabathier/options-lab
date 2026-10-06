"""Fetch HistoricalData.net's free 2022H2 end-of-day sample and keep its SPX/SPXW rows.

The archive (six months of end-of-day chains, July to December 2022) is downloadable
without an account, but its licence forbids redistributing the data, so it lands under
``cache/`` (git-ignored) and only aggregate results computed from it are committed.
Source and licence: https://historicaldata.net/options.html
"""

from __future__ import annotations

import io
import sys
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
URL = "https://historicaldata.net/file/options_sample_2022H2.zip"
CACHE = ROOT / "cache" / "eod_2022h2"
ARCHIVE = CACHE / "options_sample_2022H2.zip"
UNDERLYINGS = ("SPX", "SPXW")
TIMEOUT_SECONDS = 600


def download(destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(".part")
    with urllib.request.urlopen(URL, timeout=TIMEOUT_SECONDS) as response:
        partial.write_bytes(response.read())
    partial.replace(destination)


def main() -> int:
    if not ARCHIVE.exists():
        print(f"downloading {URL}")
        download(ARCHIVE)
    with zipfile.ZipFile(ARCHIVE) as archive:
        days = sorted(n for n in archive.namelist() if n.endswith("_options.csv"))
        if not days:
            raise SystemExit(f"{ARCHIVE} holds no day_by_date/*_options.csv files")
        for name in days:
            out = CACHE / Path(name).name
            if out.exists():
                continue
            frame = pd.read_csv(io.BytesIO(archive.read(name)), dtype={"contract": str})
            frame.loc[frame["underlying"].isin(UNDERLYINGS)].to_csv(out, index=False)
    print(f"{len(days)} sessions of SPX/SPXW quotes in {CACHE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
