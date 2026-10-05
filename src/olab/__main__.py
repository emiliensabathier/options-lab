"""Command-line entry point: ``python -m olab``."""

from __future__ import annotations

import argparse
from pathlib import Path

from olab.pipeline import run_premium, run_surface
from olab.report.build import build_report


def latest_chain(raw: Path) -> Path:
    chains = sorted(raw.glob("spx_chain_*.csv"))
    if not chains:
        raise SystemExit(f"no spx_chain_*.csv in {raw}; run scripts/capture_chain.py")
    return chains[-1]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build the options report from frozen captures")
    parser.add_argument("--raw", default="data/raw")
    parser.add_argument("--chain", help="chain CSV; defaults to the latest capture in --raw")
    parser.add_argument("--output", default="reports/options.html")
    args = parser.parse_args(argv)

    raw = Path(args.raw)
    chain = Path(args.chain) if args.chain else latest_chain(raw)
    surface = run_surface(chain, chain.with_suffix(".json"))
    premium = run_premium(raw / "vix_spx_daily.csv", raw / "vix_spx_daily.json")
    html = build_report(surface, premium)

    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(html, encoding="utf-8")
    print(f"wrote {destination} ({len(html):,} bytes)")


if __name__ == "__main__":
    main()
