"""Fetch the SPY end-of-day option archive (2008 to 2025) that lambdaclass redistributes.

Two parquet files from the ``data-v1`` release of lambdaclass/options_backtester: every SPY
option quote at each close since 2008-01-02, and the SPY daily bars. lambdaclass shares
them "for research and educational reproducibility" (their ``data/DATA_NOTICE.md``); they
took them from philippdubach/options-data, a repository announced as MIT that no longer
exists, whose upstream is undocumented (probably Alpha Vantage). Nothing here vouches for
that chain of rights, so the files land under ``cache/`` (git-ignored) and only aggregate
results computed from them are committed. Requires the GitHub CLI (``gh``).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "cache" / "spy"
REPO = "lambdaclass/options_backtester"
RELEASE = "data-v1"
FILES = ("SPY_options.parquet", "SPY_underlying.parquet")


def main() -> int:
    CACHE.mkdir(parents=True, exist_ok=True)
    missing = [name for name in FILES if not (CACHE / name).exists()]
    if missing:
        command = ["gh", "release", "download", RELEASE, "-R", REPO, "-D", str(CACHE)]
        for name in missing:
            command += ["-p", name]
        subprocess.run(command, check=True)
    print(f"{', '.join(FILES)} in {CACHE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
