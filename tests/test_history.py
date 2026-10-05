import numpy as np
import pandas as pd
import pytest

from olab.errors import DataError
from olab.premium import history as h


def _history(n=80, vix=20.0, daily=0.01):
    dates = pd.bdate_range("2020-01-01", periods=n)
    returns = np.where(np.arange(n) % 2, daily, -daily)
    # a small wobble in the VIX so the P&L has a dispersion; the first strike stays at vix
    wobble = vix * (1 + 0.02 * np.sin(np.arange(n)))
    return pd.DataFrame({"vix": wobble, "spx": 100 * np.exp(np.cumsum(returns))},
                        index=pd.Index(dates, name="date"))


def test_realized_variance_uses_only_the_next_window():
    spx = _history()["spx"]
    realized = h.forward_realized_variance(spx)
    assert len(realized) == len(spx) - h.WINDOW
    assert realized.iloc[0] == pytest.approx(0.01**2 * 252)


def test_swap_pnl_is_the_variance_gap_over_twice_the_strike():
    outcomes = h.swap_outcomes(_history())
    strike, realized = 0.2, 0.01**2 * 252
    assert outcomes["seller_pnl_vol_points"].iloc[0] == pytest.approx(
        100 * (strike**2 - realized) / (2 * strike))
    assert outcomes["realized_vol"].iloc[0] == pytest.approx(np.sqrt(realized))


def test_cap_binds_only_when_realized_exceeds_two_and_a_half_strikes():
    outcomes = h.swap_outcomes(_history(vix=5.0, daily=0.02))
    capped = 100 * (0.05**2 - (2.5 * 0.05) ** 2) / (2 * 0.05)
    assert outcomes["capped_seller_pnl_vol_points"].iloc[0] == pytest.approx(capped)
    assert (outcomes["seller_pnl_vol_points"] < outcomes["capped_seller_pnl_vol_points"]).all()


def test_non_overlapping_sampling_and_its_offsets():
    outcomes = h.swap_outcomes(_history(200))
    positions = h.non_overlapping(outcomes, 3).index.map(outcomes.index.get_loc)
    assert positions[0] == 3 and (np.diff(positions) == h.WINDOW).all()
    with pytest.raises(ValueError, match="offset"):
        h.non_overlapping(outcomes, h.WINDOW)
    assert list(h.offset_sensitivity(outcomes).index) == list(range(h.WINDOW))


def test_mincer_zarnowitz_recovers_a_known_line():
    rng = np.random.default_rng(0)
    implied = pd.Series(rng.uniform(0.01, 0.09, 500))
    realized = 0.002 + 0.8 * implied + rng.normal(0, 0.001, 500)
    reg = h.mincer_zarnowitz(implied, realized)
    assert reg.alpha == pytest.approx(0.002, abs=5e-4)
    assert reg.beta == pytest.approx(0.8, abs=0.02)
    assert reg.t_beta_equals_one < -5
    assert reg.observations == 500 and 0.9 < reg.r_squared <= 1


def test_summary_and_regimes():
    sample = h.non_overlapping(h.swap_outcomes(_history(200)))
    summary = h.summarise(sample)
    assert summary["windows"] == len(sample)
    assert summary["share_implied_above_realized"] == 1.0
    regimes = h.by_vix_regime(sample)
    assert list(regimes.index) == ["VIX < 15", "15-25", "VIX >= 25"]
    assert regimes["windows"].tolist() == [0, len(sample), 0]


def test_load_history_drops_holidays_and_the_unfinished_session(tmp_path):
    frame = _history(5)
    frame.iloc[1, frame.columns.get_loc("spx")] = np.nan
    csv = tmp_path / "h.csv"
    frame.to_csv(csv)
    loaded = h.load_history(csv, last_complete=frame.index[-1] + pd.Timedelta(hours=15))
    assert list(loaded.index) == [frame.index[0], frame.index[2], frame.index[3]]


@pytest.mark.parametrize("mutate, message", [
    (lambda f: f.drop(columns="vix"), "columns"),
    (lambda f: f.assign(vix=[np.nan, 1.0, 1.0, 1.0, 1.0]), "missing VIX"),
    (lambda f: f.iloc[::-1], "unsorted"),
])
def test_load_history_refuses_bad_files(tmp_path, mutate, message):
    csv = tmp_path / "h.csv"
    mutate(_history(5)).to_csv(csv)
    with pytest.raises(DataError, match=message):
        h.load_history(csv)
