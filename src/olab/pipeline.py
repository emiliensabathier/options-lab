"""End-to-end: the frozen captures in, everything the report shows out."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from olab.premium.history import (
    Regression,
    by_vix_regime,
    load_history,
    mincer_zarnowitz,
    non_overlapping,
    offset_sensitivity,
    summarise,
    swap_outcomes,
)
from olab.snapshot import Snapshot, load_snapshot
from olab.surface.arbitrage import between_pillars, split_violations, tradable_chain_arbitrage
from olab.surface.quotes import MIN_MATURITY, SurfaceQuotes, build_quotes, is_stale, screen_quotes
from olab.surface.svi import fit_errors, fit_essvi, fit_ssvi, fit_svi_surface
from olab.surface.varswap import THIRTY_DAYS, cboe_vix, replicated_variance

MODEL_NOTES = {
    "SVI per slice": "five free parameters per expiry, no constraint",
    "SVI + penalties": "the open-source approach: Durrleman and calendar penalties",
    "SSVI": "power-law surface, three shared parameters, arbitrage-free by theorem",
    "eSSVI": "SSVI shape per expiry, chained by wing-slope constraints",
}
ARBITRAGE_FREE = ("SSVI", "eSSVI")  # audited between pillars too
DENSE_MATURITIES = 400


@dataclass(frozen=True)
class ModelResult:
    """How one surface model fits, what arbitrage it leaves, what thirty-day vol it implies."""

    name: str
    errors: dict[str, float]
    violations: dict[str, int]
    replicated_vix: float


@dataclass(frozen=True)
class SurfaceOutput:
    snapshot: Snapshot
    quotes: SurfaceQuotes
    chain_arbitrage: dict[str, dict[str, int]]
    models: dict[str, ModelResult]
    between_pillars: dict[str, dict[str, int]]
    surfaces: dict[str, object]
    cboe: dict


@dataclass(frozen=True)
class PremiumOutput:
    outcomes: pd.DataFrame
    sample: pd.DataFrame  # the non-overlapping windows every headline number is read from
    headline: dict[str, float]
    sensitivity: pd.DataFrame
    regression: Regression
    regimes: pd.DataFrame


def _model_iv(surface, table: pd.DataFrame) -> np.ndarray:
    iv = np.empty(len(table))
    for maturity, group in table.groupby("T"):
        iv[group.index.to_numpy()] = surface.implied_vol(group["k"].to_numpy(), maturity)
    return iv


def _evaluate(name: str, surface, table: pd.DataFrame) -> ModelResult:
    ranges = table.groupby("T")["k"].agg(["min", "max"])
    slices = [surface.slice(maturity) for maturity in ranges.index]
    return ModelResult(
        name=name,
        errors=fit_errors(table, _model_iv(surface, table)),
        violations=split_violations(slices, list(ranges.itertuples(index=False, name=None))),
        replicated_vix=100.0 * float(np.sqrt(replicated_variance(surface.slice(THIRTY_DAYS),
                                                                 THIRTY_DAYS))),
    )


def run_surface(chain_csv: Path, meta_json: Path) -> SurfaceOutput:
    """Quotes to forwards to four fitted surfaces, each audited the same way."""
    snapshot = load_snapshot(chain_csv, meta_json)
    quotes = build_quotes(snapshot.quotes, snapshot.spot, snapshot.as_of)
    table = quotes.table

    svi = fit_svi_surface(table, constrained=False)
    surfaces = {
        "SVI per slice": svi,
        "SVI + penalties": fit_svi_surface(table, constrained=True),
        "SSVI": fit_ssvi(table, {t: float(s.total_variance(0.0)) for t, s in svi.slices.items()}),
        "eSSVI": fit_essvi(table, svi),
    }
    models = {name: _evaluate(name, surface, table) for name, surface in surfaces.items()}
    dense = np.linspace(table["T"].min(), table["T"].max(), DENSE_MATURITIES)
    any_age, _ = screen_quotes(snapshot.quotes.loc[snapshot.quotes["T"] >= MIN_MATURITY])
    discounts = {expiry: fwd.discount for expiry, fwd in quotes.forwards.items()}
    return SurfaceOutput(
        snapshot=snapshot,
        quotes=quotes,
        chain_arbitrage={
            "Screened, any quote age": tradable_chain_arbitrage(any_age),
            "Screened, last trade within 30 days": tradable_chain_arbitrage(quotes.screened),
            "Out-of-the-money side only": tradable_chain_arbitrage(table),
        },
        models=models,
        between_pillars={name: between_pillars(surfaces[name], dense) for name in ARBITRAGE_FREE},
        surfaces=surfaces,
        # zero bids stay in: the recipe's truncation rule reads them
        cboe=cboe_vix(snapshot.quotes.loc[~is_stale(snapshot.quotes, snapshot.as_of)], discounts),
    )


def run_premium(history_csv: Path, meta_json: Path) -> PremiumOutput:
    """Thirty-day variance swaps struck at the VIX close, every day since 1990."""
    fetched = pd.Timestamp(json.loads(meta_json.read_text(encoding="utf-8"))["fetched_at_utc"])
    # the capture's own date is an unfinished session; its "close" is an intraday print
    history = load_history(history_csv, last_complete=fetched.tz_convert(None))
    outcomes = swap_outcomes(history)
    sample = non_overlapping(outcomes)
    return PremiumOutput(
        outcomes=outcomes,
        sample=sample,
        headline=summarise(sample),
        sensitivity=offset_sensitivity(outcomes),
        regression=mincer_zarnowitz(sample["implied_vol"] ** 2, sample["realized_vol"] ** 2),
        regimes=by_vix_regime(sample),
    )
