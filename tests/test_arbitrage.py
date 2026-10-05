import numpy as np
import pandas as pd

from olab.surface.arbitrage import (
    K_GRID,
    between_pillars,
    butterfly_violations,
    calendar_violations,
    durrleman_g,
    split_violations,
    tradable_chain_arbitrage,
)


def flat(w):
    return lambda k: np.full_like(np.asarray(k, dtype=float), w)


def test_flat_smile_has_a_positive_density_everywhere():
    assert (durrleman_g(flat(0.01)) > 0).all()
    assert butterfly_violations(flat(0.01)) == 0


def test_a_too_steep_wing_and_negative_variance_are_both_caught():
    def steep(k):  # wing slope above Lee's bound of 2
        return 0.01 + 5.0 * np.abs(k)

    assert butterfly_violations(steep) > 0
    assert butterfly_violations(flat(-0.01)) == len(K_GRID)


def test_calendar_counts_points_where_variance_falls_with_time():
    assert calendar_violations([flat(0.01), flat(0.02)]) == 0
    assert calendar_violations([flat(0.02), flat(0.01)]) == len(K_GRID)


def test_split_separates_quoted_from_extrapolated_strikes():
    k = np.linspace(-0.6, 0.6, 13)

    def wing(x):
        return np.where(np.abs(x) > 0.25, -1.0, 0.01)

    counts = split_violations([wing, flat(0.005)], [(-0.25, 0.25), (-0.15, 0.15)], k=k)
    assert counts["butterfly_quoted"] == 0
    assert counts["butterfly_extrapolated"] == 8  # |k| >= 0.3
    # slice two lies below slice one where slice one is positive: |k| <= 0.2
    assert counts["calendar_quoted"] == 3
    assert counts["calendar_extrapolated"] == 2


def _side(kind, bid, ask, expiry="e", strikes=(90.0, 100.0, 110.0)):
    return pd.DataFrame({"expiry": expiry, "kind": kind, "strike": list(strikes),
                         "bid": bid, "ask": ask})


def test_clean_chain_has_no_executable_arbitrage():
    chain = pd.concat([_side("C", [11.0, 6.0, 1.0], [11.5, 6.5, 1.5]),
                       _side("P", [1.0, 3.0, 8.0], [1.5, 3.5, 8.5])])
    assert tradable_chain_arbitrage(chain) == {"vertical": 0, "butterfly": 0,
                                               "checked_expiries": 1}


def test_executable_vertical_and_butterfly_are_counted_per_type():
    # the 90 call can be bought below the 100 call's bid
    calls = _side("C", [5.0, 6.0, 1.0], [5.5, 6.5, 1.5])
    # the 100 put's bid tops the wings' asks
    puts = _side("P", [1.0, 6.0, 8.0], [1.5, 6.5, 8.5])
    thin = _side("C", [1.0, 1.0], [2.0, 2.0], expiry="thin", strikes=(1.0, 2.0))
    found = tradable_chain_arbitrage(pd.concat([calls, puts, thin]))
    assert found == {"vertical": 1, "butterfly": 2, "checked_expiries": 2}


class _Surface:
    def __init__(self, variance_of_t):
        self.variance_of_t = variance_of_t

    def slice(self, maturity):
        return flat(self.variance_of_t(maturity))


def test_between_pillars_audits_every_interpolated_maturity():
    maturities = np.linspace(0.1, 1.0, 10)
    assert between_pillars(_Surface(lambda t: 0.04 * t), maturities) == {
        "maturities": 10, "butterfly": 0, "calendar": 0}
    # variance falling with time breaks calendar on every point of every pair
    found = between_pillars(_Surface(lambda t: 0.05 - 0.04 * t), maturities)
    assert found["calendar"] == 9 * len(K_GRID) and found["butterfly"] == 0
