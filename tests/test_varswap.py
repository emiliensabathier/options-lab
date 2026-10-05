import numpy as np
import pandas as pd
import pytest

from conftest import black_chain
from olab.errors import CalibrationError, DataError
from olab.surface.varswap import (
    THIRTY_DAYS,
    _bracketing,
    cboe_term_variance,
    cboe_vix,
    replicated_variance,
)

DENSE = np.arange(40.0, 160.5, 0.5)


def test_flat_smile_replicates_its_own_variance():
    w = 0.2**2 * THIRTY_DAYS
    fair = replicated_variance(lambda k: np.full_like(k, w), THIRTY_DAYS)
    assert fair == pytest.approx(0.04, rel=1e-5)  # trapezoid error on 8001 points


def test_cboe_term_on_a_dense_flat_chain_is_close_to_sigma_squared():
    chain = black_chain(discount=0.995, maturity=0.08, strikes=DENSE, half_spread=1e-4)
    term = cboe_term_variance(chain, 0.995)
    assert np.sqrt(term.variance) == pytest.approx(0.2, abs=2e-3)
    assert term.lowest_strike < 85 and term.highest_strike > 115


def test_strip_stops_after_two_zero_bids():
    chain = black_chain(maturity=0.08, strikes=np.arange(50.0, 151.0, 1.0))
    term = cboe_term_variance(chain, 0.99)
    otm = chain.loc[(chain["kind"] == "P") & (chain["strike"] < 100)]
    last_dead = otm.loc[otm["bid"] <= 0, "strike"].max()
    assert term.lowest_strike > last_dead


def test_vix_blends_the_two_bracketing_expiries_to_thirty_days():
    near = black_chain(maturity=25 / 365, vol=0.18, expiry="near", strikes=DENSE,
                       half_spread=1e-4)
    nxt = black_chain(maturity=32 / 365, vol=0.22, expiry="next", strikes=DENSE,
                      half_spread=1e-4)
    chain = pd.concat([near, nxt])
    result = cboe_vix(chain, {"near": 0.99, "next": 0.99})
    assert (result["near"].expiry, result["next"].expiry) == ("near", "next")
    # 30 days sits 5/7 of the way from 25 to 32 days in variance-time
    expected = np.sqrt((25 * 0.18**2 * 2 / 7 + 32 * 0.22**2 * 5 / 7) / 30) * 100
    assert result["vix"] == pytest.approx(expected, abs=0.3)
    with pytest.raises(CalibrationError, match="discount"):
        cboe_vix(chain, {"near": 0.99})


def test_bracketing_needs_one_expiry_each_side_of_thirty_days():
    with pytest.raises(DataError, match="brackets"):
        _bracketing(pd.Series([25 / 365], index=["a"]))


def test_centre_strike_needs_both_a_call_and_a_put():
    chain = black_chain(maturity=0.08)
    no_atm_put = chain.loc[~((chain["kind"] == "P") & (chain["strike"] == 100.0))]
    with pytest.raises(DataError, match="lacks a call or a put"):
        cboe_term_variance(no_atm_put, 0.99)
