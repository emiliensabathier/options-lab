import numpy as np
import pytest

from conftest import black_chain
from olab.surface.forwards import implied_forward, trimmed_fit


def test_parity_recovers_forward_and_discount():
    chain = black_chain(forward=101.5, discount=0.985)
    fwd, reason = implied_forward(chain, spot=100.0)
    assert reason is None
    assert fwd.forward == pytest.approx(101.5, abs=1e-6)
    assert fwd.discount == pytest.approx(0.985, abs=1e-8)
    assert fwd.rate == pytest.approx(-np.log(0.985) / 0.25)


def test_stale_pairs_are_trimmed_not_averaged_in():
    chain = black_chain(forward=100.0, discount=0.99)
    stale = (chain["kind"] == "C") & chain["strike"].isin([97.0, 98.0, 103.0])
    chain.loc[stale, ["bid", "ask"]] += 8.0  # a quote frozen weeks ago
    fwd, _ = implied_forward(chain, spot=100.0)
    assert fwd.trimmed == 3
    assert fwd.forward == pytest.approx(100.0, abs=1e-6)


def test_scattered_outliers_are_dropped_and_the_line_is_exact():
    strikes = np.arange(90.0, 111.0)
    spread = 0.99 * (100.0 - strikes)
    spread[[2, 9, 17]] += [12.0, -9.0, 15.0]
    slope, intercept, kept = trimmed_fit(strikes, spread)
    assert list(np.flatnonzero(~kept)) == [2, 9, 17]
    assert slope == pytest.approx(-0.99)
    assert intercept == pytest.approx(99.0)


def test_trimming_gives_up_rather_than_fit_a_handful_of_pairs():
    strikes = np.arange(95.0, 101.0)
    spread = 0.99 * (100.0 - strikes)
    spread[[1, 4]] += [10.0, -10.0]
    _, _, kept = trimmed_fit(strikes, spread)
    assert kept.sum() < 5


def test_too_few_pairs_is_a_named_refusal():
    chain = black_chain(strikes=[99.0, 100.0, 101.0])
    assert implied_forward(chain, spot=100.0) == (None, "too_few_parity_pairs")


def test_implausible_discount_is_a_named_refusal():
    chain = black_chain(discount=0.5)
    assert implied_forward(chain, spot=100.0) == (None, "discount_out_of_range")


FORWARD, DISCOUNT = 100.0, 0.95
SPOT = FORWARD * DISCOUNT  # no dividend


def american_chain():
    """In-the-money puts floored at exercise value, as an American chain quotes them."""
    chain = black_chain(forward=FORWARD, discount=DISCOUNT, vol=0.08)
    itm_put = (chain["kind"] == "P") & (chain["strike"] > SPOT)
    floor = chain.loc[itm_put, "strike"] - SPOT
    chain.loc[itm_put, "bid"] = np.maximum(chain.loc[itm_put, "bid"], floor)
    chain.loc[itm_put, "ask"] = np.maximum(chain.loc[itm_put, "ask"], floor + 0.02)
    return chain


def test_early_exercise_bends_the_parity_line_when_the_discount_is_read_off_it():
    fwd, reason = implied_forward(american_chain(), spot=SPOT)
    assert reason == "discount_out_of_range" or abs(fwd.discount - DISCOUNT) > 1e-3


def test_a_given_rate_pins_the_discount_and_reads_the_forward_below_spot():
    rate = -np.log(DISCOUNT) / 0.25
    fwd, reason = implied_forward(american_chain(), spot=SPOT, rate=rate)
    assert reason is None
    assert fwd.discount == pytest.approx(DISCOUNT)
    # a cent: far puts priced under the half-spread have their bid floored at zero
    assert fwd.forward == pytest.approx(FORWARD, abs=0.01)


def test_a_given_rate_still_needs_pairs_below_spot():
    chain = black_chain(strikes=[100.0, 101.0, 102.0, 103.0, 104.0, 105.0])
    assert implied_forward(chain, spot=100.0, rate=0.04) == (None, "too_few_parity_pairs")
