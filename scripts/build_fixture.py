"""Freeze a small slice of the captured chain, and the numbers the pipeline gets from it.

The regression test runs the whole surface pipeline on six expiries instead of forty-odd,
so it finishes in seconds, and checks every headline number against the values frozen here.
Rerun this only after a deliberate methodology change, and say so in the commit.

    python scripts/build_fixture.py
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from olab.pipeline import run_premium, run_surface

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
FIXTURES = ROOT / "tests" / "fixtures"
# one week, the two expiries the VIX recipe brackets thirty days with, and three later ones
EXPIRIES = ("2026-10-12", "2026-11-03", "2026-11-04", "2026-11-06", "2026-12-18", "2027-03-19")


def surface_numbers(output) -> dict:
    return {
        "cboe_vix": output.cboe["vix"],
        "forwards": {e: f.forward for e, f in output.quotes.forwards.items()},
        "discounts": {e: f.discount for e, f in output.quotes.forwards.items()},
        "refused": dict(output.quotes.refused),
        "chain_arbitrage": output.chain_arbitrage,
        "models": {name: asdict(model) for name, model in output.models.items()},
    }


def premium_numbers(output) -> dict:
    return {
        "headline": output.headline,
        "regression": asdict(output.regression),
    }


def main() -> None:
    chain = sorted(RAW.glob("spx_chain_*.csv"))[-1]
    FIXTURES.mkdir(parents=True, exist_ok=True)
    quotes = pd.read_csv(chain)
    subset = quotes.loc[quotes["expiry"].isin(EXPIRIES)]
    subset.to_csv(FIXTURES / "spx_chain_fixture.csv", index=False)
    shutil.copyfile(chain.with_suffix(".json"), FIXTURES / "spx_chain_fixture.json")

    surface = run_surface(FIXTURES / "spx_chain_fixture.csv", FIXTURES / "spx_chain_fixture.json")
    premium = run_premium(RAW / "vix_spx_daily.csv", RAW / "vix_spx_daily.json")
    expected = {"surface": surface_numbers(surface), "premium": premium_numbers(premium)}
    (FIXTURES / "expected.json").write_text(json.dumps(expected, indent=2), encoding="utf-8")
    print(f"{len(subset):,} quotes, expected numbers written to {FIXTURES / 'expected.json'}")


if __name__ == "__main__":
    main()
