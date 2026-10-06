import pandas as pd
import pytest

from olab.eod import load_eod_day
from olab.errors import DataError


def eod_rows(**overrides) -> pd.DataFrame:
    """Synthetic end-of-day rows in the archive's layout (no real quote is reproduced)."""
    rows = [
        {"contract": "SPXW221021C04000000", "underlying": "SPXW", "expiration": "2022-10-21",
         "type": "call", "strike": 4000.0, "quote_date": "2022-10-14", "bid": 10.0,
         "ask": 11.0, "last_trade_date": "2022-10-14", "underlying_close": 3583.07,
         "settlement_time": "PM"},
        {"contract": "SPXW221021P03500000", "underlying": "SPXW", "expiration": "2022-10-21",
         "type": "put", "strike": 3500.0, "quote_date": "2022-10-14", "bid": None,
         "ask": 0.05, "last_trade_date": None, "underlying_close": 3583.07,
         "settlement_time": "PM"},
        {"contract": "SPX221021P03500000", "underlying": "SPX", "expiration": "2022-10-21",
         "type": "put", "strike": 3500.0, "quote_date": "2022-10-14", "bid": 20.0,
         "ask": None, "last_trade_date": "2022-08-01", "underlying_close": 3583.07,
         "settlement_time": "AM"},
        {"contract": "SPX221118C03600000", "underlying": "SPX", "expiration": "2022-11-18",
         "type": "call", "strike": 3600.0, "quote_date": "2022-10-14", "bid": 90.0,
         "ask": 92.0, "last_trade_date": "2022-10-13", "underlying_close": 3583.07,
         "settlement_time": "AM"},
    ]
    frame = pd.DataFrame(rows)
    return frame.assign(**overrides)


def test_maps_the_archive_layout_onto_a_snapshot_at_the_close(tmp_path):
    path = tmp_path / "2022-10-14_options.csv"
    eod_rows().to_csv(path, index=False)

    snapshot = load_eod_day(path, vix_close=31.94)

    assert snapshot.as_of == pd.Timestamp("2022-10-14 16:00", tz="America/New_York")
    assert snapshot.spot == pytest.approx(3583.07)
    assert snapshot.levels == {"^SPX": 3583.07, "^VIX": 31.94}
    quotes = snapshot.quotes
    assert set(quotes["kind"]) == {"C", "P"}
    # one root per expiry: SPXW where listed, so the AM SPX row on 10-21 is dropped
    assert sorted(zip(quotes["expiry"], quotes["root"], strict=True)) == [
        ("2022-10-21", "SPXW"), ("2022-10-21", "SPXW"), ("2022-11-18", "SPX")]


def test_a_blank_bid_is_a_zero_bid_and_a_blank_last_trade_is_stale(tmp_path):
    path = tmp_path / "day.csv"
    eod_rows().to_csv(path, index=False)

    quotes = load_eod_day(path).quotes
    put = quotes.loc[quotes["strike"] == 3500.0].iloc[0]

    assert put["bid"] == 0.0
    assert pd.isna(pd.to_datetime(put["lastTradeDate"], utc=True))


def test_a_quote_with_no_ask_is_not_a_quote(tmp_path):
    path = tmp_path / "day.csv"
    eod_rows(underlying="SPX", contract=[
        "SPX221021C04000000", "SPX221021P03600000", "SPX221021P03500000",
        "SPX221118C03600000"]).to_csv(path, index=False)

    quotes = load_eod_day(path).quotes

    assert quotes["ask"].notna().all()
    assert len(quotes) == 3


def test_last_trade_is_read_at_the_close_of_its_day(tmp_path):
    path = tmp_path / "day.csv"
    eod_rows().to_csv(path, index=False)

    quotes = load_eod_day(path).quotes
    call = quotes.loc[quotes["strike"] == 4000.0].iloc[0]

    assert pd.Timestamp(call["lastTradeDate"]) == pd.Timestamp(
        "2022-10-14 16:00", tz="America/New_York")


def test_maturities_follow_each_roots_settlement(tmp_path):
    path = tmp_path / "day.csv"
    eod_rows().to_csv(path, index=False)

    quotes = load_eod_day(path).quotes
    weekly = quotes.loc[quotes["expiry"] == "2022-10-21", "T"].iloc[0]

    assert weekly * 365.0 == pytest.approx(7.0)


def test_refuses_a_day_with_several_quote_dates(tmp_path):
    path = tmp_path / "day.csv"
    eod_rows(quote_date=["2022-10-14", "2022-10-14", "2022-10-13", "2022-10-14"]).to_csv(
        path, index=False)

    with pytest.raises(DataError, match="quote dates"):
        load_eod_day(path)


def test_refuses_a_day_without_an_index_close(tmp_path):
    path = tmp_path / "day.csv"
    eod_rows(underlying_close=None).to_csv(path, index=False)

    with pytest.raises(DataError, match="close"):
        load_eod_day(path)
