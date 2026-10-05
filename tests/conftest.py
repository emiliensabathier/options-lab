from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from olab.black import black_price
from olab.pipeline import run_premium, run_surface

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
RAW = ROOT / "data" / "raw"
AS_OF = pd.Timestamp("2026-10-05 16:00", tz="UTC")


def black_chain(
    forward: float = 100.0,
    discount: float = 0.99,
    maturity: float = 0.25,
    vol=0.2,
    strikes=None,
    half_spread: float = 0.01,
    expiry: str = "2027-01-04",
) -> pd.DataFrame:
    """A clean European chain priced with Black-76, calls and puts on every strike.

    ``vol`` may be a number or a function of log-moneyness, for a smile.
    """
    strikes = np.arange(70.0, 131.0, 1.0) if strikes is None else np.asarray(strikes, float)
    sigma = vol(np.log(strikes / forward)) if callable(vol) else np.full_like(strikes, vol)
    rows = []
    for kind in ("C", "P"):
        mid = discount * black_price(forward, strikes, maturity, sigma, kind == "C")
        for strike, price in zip(strikes, mid, strict=True):
            rows.append({
                "expiry": expiry, "T": maturity, "strike": strike, "kind": kind,
                "bid": max(price - half_spread, 0.0), "ask": price + half_spread,
                "lastTradeDate": "2026-10-02 18:00:00+00:00",
            })
    return pd.DataFrame(rows)


def smile_table(slices) -> pd.DataFrame:
    """Quotes read off known total-variance curves, one slice per ``(maturity, curve)``."""
    k = np.linspace(-0.3, 0.2, 26)
    frames = []
    for maturity, curve in slices:
        iv = np.sqrt(curve(k) / maturity)
        frames.append(pd.DataFrame({
            "expiry": f"T{maturity:.3f}", "T": maturity, "k": k,
            "iv": iv, "iv_bid": iv - 0.005, "iv_ask": iv + 0.005,
        }))
    return pd.concat(frames, ignore_index=True)


@pytest.fixture(scope="session")
def surface_output():
    """The surface pipeline on the frozen six-expiry fixture, run once per session."""
    return run_surface(FIXTURES / "spx_chain_fixture.csv", FIXTURES / "spx_chain_fixture.json")


@pytest.fixture(scope="session")
def premium_output():
    return run_premium(RAW / "vix_spx_daily.csv", RAW / "vix_spx_daily.json")
