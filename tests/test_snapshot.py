import json

import pandas as pd
import pytest

from olab.errors import DataError
from olab.snapshot import load_snapshot, select_roots, settlement


def _write(tmp_path, rows, levels=None):
    chain = tmp_path / "chain.csv"
    pd.DataFrame(rows).to_csv(chain, index=False)
    meta = tmp_path / "chain.json"
    levels = [{"symbol": "^SPX", "last": 7000.0}] if levels is None else levels
    meta.write_text(json.dumps({"captured_from_utc": "2026-10-05T16:00:00+00:00",
                                "levels": levels}), encoding="utf-8")
    return chain, meta


def _row(symbol, expiry, kind, strike=7000.0):
    return {"contractSymbol": symbol, "strike": strike, "bid": 1.0, "ask": 1.2,
            "expiry": expiry, "kind": kind, "lastTradeDate": "2026-10-05 15:00:00+00:00"}


def test_weekly_and_monthly_settle_six_and_a_half_hours_apart():
    gap = settlement("2026-10-16", "SPXW") - settlement("2026-10-16", "SPX")
    assert gap == pd.Timedelta(hours=6, minutes=30)


def test_one_root_per_expiry_weekly_preferred():
    quotes = pd.DataFrame({"expiry": ["a", "a", "b"], "root": ["SPX", "SPXW", "SPX"]})
    kept = select_roots(quotes)
    assert kept.to_dict("list") == {"expiry": ["a", "b"], "root": ["SPXW", "SPX"]}


def test_load_snapshot_sets_maturity_from_the_settlement_clock(tmp_path):
    chain, meta = _write(tmp_path, [_row("SPXW261012C07000000", "2026-10-12", "C")])
    snap = load_snapshot(chain, meta)
    expected = (settlement("2026-10-12", "SPXW") - snap.as_of).total_seconds() / (365 * 86400)
    assert snap.quotes["T"].iloc[0] == pytest.approx(expected)
    assert snap.spot == 7000.0


def test_unparseable_symbol_is_refused(tmp_path):
    chain, meta = _write(tmp_path, [_row("BAD", "2026-10-12", "C")])
    with pytest.raises(DataError, match="do not parse"):
        load_snapshot(chain, meta)


def test_symbol_disagreeing_with_its_type_is_refused(tmp_path):
    chain, meta = _write(tmp_path, [_row("SPXW261012C07000000", "2026-10-12", "P")])
    with pytest.raises(DataError, match="disagree"):
        load_snapshot(chain, meta)


def test_missing_spot_level_is_refused(tmp_path):
    chain, meta = _write(tmp_path, [_row("SPXW261012C07000000", "2026-10-12", "C")], levels=[])
    with pytest.raises(DataError, match="SPX"):
        load_snapshot(chain, meta)


def test_missing_column_is_refused(tmp_path):
    chain, meta = _write(tmp_path, [{"contractSymbol": "x"}])
    with pytest.raises(DataError, match="lacks columns"):
        load_snapshot(chain, meta)
