import numpy as np
import pandas as pd
import pytest

from conftest import AS_OF, black_chain
from olab.surface.quotes import build_quotes, is_stale, screen_quotes


def test_screen_counts_every_quote_it_drops():
    chain = black_chain().iloc[:6].copy()
    chain.loc[chain.index[0], "bid"] = 0.0
    chain.loc[chain.index[1], ["bid", "ask"]] = [2.0, 1.0]
    chain.loc[chain.index[2], ["bid", "ask"]] = [1.0, 3.0]
    chain.loc[chain.index[3], "lastTradeDate"] = "2026-07-01 15:00:00+00:00"
    kept, refused = screen_quotes(chain, AS_OF)
    assert dict(refused) == {"no_bid": 1, "crossed": 1, "stale_last_trade": 1,
                             "spread_too_wide": 1}
    assert len(kept) == 2


def test_staleness_is_skipped_without_a_capture_time():
    chain = black_chain().iloc[:2].assign(lastTradeDate="2020-01-01 00:00:00+00:00")
    assert len(screen_quotes(chain)[0]) == 2
    assert is_stale(chain, AS_OF).all()


def test_build_quotes_recovers_the_smile_it_was_priced_with():
    smile = lambda k: 0.2 - 0.3 * k + 0.5 * k**2  # noqa: E731
    chain = black_chain(vol=smile, half_spread=0.005)
    sq = build_quotes(chain, spot=100.0, as_of=AS_OF)
    table = sq.table
    assert set(table["kind"]) == {"C", "P"}
    assert ((table["kind"] == "C") == (table["strike"] >= 100.0)).all()
    np.testing.assert_allclose(table["iv"], smile(table["k"]), atol=1e-8)
    assert (table["iv_bid"] < table["iv"]).all() and (table["iv"] < table["iv_ask"]).all()
    assert sq.refused["in_the_money_side"] == len(chain) // 2


def test_short_maturities_and_unfittable_expiries_are_ledgered():
    week = black_chain(maturity=3 / 365, expiry="2026-10-08")
    thin = black_chain(strikes=[99.0, 100.0], expiry="2026-11-20")
    sq = build_quotes(pd.concat([week, thin, black_chain()]), spot=100.0, as_of=AS_OF)
    assert sq.refused["maturity_under_7_days"] == len(week)
    assert sq.refused["expiry_too_few_parity_pairs"] == len(thin)
    assert list(sq.forwards) == ["2027-01-04"]


def test_far_strikes_are_refused_beyond_the_moneyness_range():
    # two years at 50% vol keeps a bid on the strike-40 put, so only moneyness refuses it
    strikes = [40.0, 95.0, 96.0, 97.0, 98.0, 99.0, 100.0, 101.0, 102.0]
    chain = black_chain(strikes=strikes, maturity=2.0, vol=0.5)
    sq = build_quotes(chain, spot=100.0, as_of=AS_OF)
    assert sq.refused["beyond_moneyness_range"] == 1
    assert sq.table["strike"].min() == pytest.approx(95.0)
