"""Loading of the frozen SPX option-chain capture.

One expiry date can carry two contracts: the AM-settled monthly (root ``SPX``), settled on
the opening print, and the PM-settled weekly (root ``SPXW``), settled on the close. They are
six and a half hours apart, so mixing them in one slice would merge two maturities. Each
slice keeps one root: ``SPXW`` wherever it is listed, ``SPX`` only where it is the sole
contract, and each root's own settlement time sets its maturity.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from olab.errors import DataError

NEW_YORK = "America/New_York"
SETTLEMENT_TIME = {"SPXW": "16:00", "SPX": "09:30"}
SECONDS_PER_YEAR = 365.0 * 24 * 3600
SYMBOL = r"^(?P<root>SPXW?)(?P<yymmdd>\d{6})(?P<kind>[CP])(?P<strike>\d{8})$"
REQUIRED = ("contractSymbol", "strike", "bid", "ask", "expiry", "kind")


@dataclass(frozen=True)
class Snapshot:
    """A chain capture and the index levels read alongside it."""

    quotes: pd.DataFrame
    as_of: pd.Timestamp
    spot: float
    levels: dict[str, float]


def parse_symbols(quotes: pd.DataFrame) -> pd.DataFrame:
    parsed = quotes["contractSymbol"].str.extract(SYMBOL)
    unparsed = parsed["root"].isna()
    if unparsed.any():
        sample = quotes.loc[unparsed, "contractSymbol"].head(3).tolist()
        raise DataError(f"{int(unparsed.sum())} contract symbols do not parse, e.g. {sample}")
    mismatched = parsed["kind"] != quotes["kind"]
    if mismatched.any():
        raise DataError(f"{int(mismatched.sum())} quotes disagree with their symbol's type")
    return quotes.assign(root=parsed["root"])


def select_roots(quotes: pd.DataFrame) -> pd.DataFrame:
    """Keep one settlement convention per expiry: ``SPXW`` where listed, else ``SPX``."""
    has_weekly = quotes.groupby("expiry")["root"].transform(lambda r: (r == "SPXW").any())
    keep = (quotes["root"] == "SPXW") | ~has_weekly
    return quotes.loc[keep].reset_index(drop=True)


def settlement(expiry: str, root: str) -> pd.Timestamp:
    """Settlement instant of a contract, in UTC."""
    local = pd.Timestamp(f"{expiry} {SETTLEMENT_TIME[root]}").tz_localize(NEW_YORK)
    return local.tz_convert("UTC")


def year_fractions(quotes: pd.DataFrame, as_of: pd.Timestamp) -> pd.Series:
    """Time to settlement in years, ACT/365 on the clock rather than on dates."""
    pairs = quotes[["expiry", "root"]].drop_duplicates()
    instants = {(e, r): settlement(e, r) for e, r in pairs.itertuples(index=False)}
    seconds = [
        (instants[(e, r)] - as_of).total_seconds()
        for e, r in zip(quotes["expiry"], quotes["root"], strict=True)
    ]
    return pd.Series(seconds, index=quotes.index) / SECONDS_PER_YEAR


def load_snapshot(chain_csv: Path, meta_json: Path) -> Snapshot:
    """Read a capture written by ``scripts/capture_chain.py``."""
    quotes = pd.read_csv(chain_csv, dtype={"expiry": str})
    missing = [c for c in REQUIRED if c not in quotes.columns]
    if missing:
        raise DataError(f"chain capture lacks columns {missing}")
    meta = json.loads(Path(meta_json).read_text(encoding="utf-8"))
    levels = {item["symbol"]: float(item["last"]) for item in meta["levels"]}
    if "^SPX" not in levels:
        raise DataError("capture metadata carries no ^SPX level")

    as_of = pd.Timestamp(meta["captured_from_utc"]).tz_convert("UTC")
    quotes = select_roots(parse_symbols(quotes))
    quotes = quotes.assign(T=year_fractions(quotes, as_of))
    return Snapshot(quotes=quotes, as_of=as_of, spot=levels["^SPX"], levels=levels)
