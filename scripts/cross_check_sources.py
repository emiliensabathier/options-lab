"""Compare the two archives' SPY quotes on the sessions they share (July to December 2022).

HistoricalData.net's 2022H2 sample carries SPY chains alongside SPX; the lambdaclass
archive carries SPY alone. Matching contracts by OCC symbol on each common session and
comparing bid and ask says whether the two are independent records or one feed twice.
Only counts and differences are written; no quote leaves ``cache/``.
"""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
HD_ARCHIVE = ROOT / "cache" / "eod_2022h2" / "options_sample_2022H2.zip"
SPY_OPTIONS = ROOT / "cache" / "spy" / "SPY_options.parquet"
OUTPUT = ROOT / "data" / "panel" / "cross_check_spy_2022h2.csv"
HD_COLUMNS = ["contract", "underlying", "bid", "ask"]


def compare(hd: pd.DataFrame, lc: pd.DataFrame) -> dict:
    """Counts of matched contracts and of equal sides; a blank HD bid is a zero bid."""
    merged = hd.merge(lc, on="contract", suffixes=("_hd", "_lc"))
    bid_hd = merged["bid_hd"].fillna(0.0)
    both_asks = merged["ask_hd"].notna()
    return {
        "hd_rows": len(hd),
        "lc_rows": len(lc),
        "matched": len(merged),
        "bid_equal": int((bid_hd == merged["bid_lc"]).sum()),
        "ask_equal": int((merged.loc[both_asks, "ask_hd"] == merged.loc[both_asks, "ask_lc"])
                         .sum()),
        "max_abs_diff": float(max((bid_hd - merged["bid_lc"]).abs().max(),
                                  (merged["ask_hd"] - merged["ask_lc"]).abs().max())),
    }


def main() -> int:
    rows = []
    with zipfile.ZipFile(HD_ARCHIVE) as archive:
        for name in sorted(n for n in archive.namelist() if n.endswith("_options.csv")):
            day = Path(name).name.split("_")[0]
            hd = pd.read_csv(io.BytesIO(archive.read(name)), usecols=HD_COLUMNS,
                             dtype={"contract": str})
            hd = hd.loc[hd["underlying"] == "SPY"].drop(columns="underlying")
            lc = pq.read_table(SPY_OPTIONS, columns=["contract_id", "bid", "ask"],
                               filters=[("date", "==", pd.Timestamp(day))]).to_pandas()
            if hd.empty or lc.empty:
                continue
            row = {"date": day, **compare(hd, lc.rename(columns={"contract_id": "contract"}))}
            rows.append(row)
            print(row, flush=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(OUTPUT, index=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
