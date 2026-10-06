import pandas as pd
import pytest

from olab.errors import DataError
from olab.spy import load_spy_day

DAY = "2022-10-14"


def spy_rows() -> pd.DataFrame:
    """Synthetic rows in the SPY archive's layout (no real quote is reproduced)."""
    day = pd.Timestamp(DAY)
    rows = [
        ("SPY221021C00360000", "2022-10-21", 360.0, "call", 3.0, 3.1),
        ("SPY221021P00350000", "2022-10-21", 350.0, "put", 0.0, 0.05),
        ("SPY221021P00340000", "2022-10-21", 340.0, "put", 0.0, 0.0),
        ("SPY231215C00400000", "2023-12-15", 400.0, "call", 9.0, 9.4),
        ("SPY221017C00360000", "2022-10-17", 360.0, "call", 1.0, 1.1),
    ]
    frame = pd.DataFrame(rows, columns=["contract_id", "expiration", "strike", "type", "bid",
                                        "ask"])
    other_day = frame.iloc[[0]].assign(bid=99.0)
    return pd.concat([
        frame.assign(date=day, expiration=pd.to_datetime(frame["expiration"])),
        other_day.assign(date=pd.Timestamp("2022-10-13"),
                         expiration=pd.to_datetime(other_day["expiration"])),
    ], ignore_index=True)


@pytest.fixture
def archive(tmp_path):
    options = tmp_path / "SPY_options.parquet"
    underlying = tmp_path / "SPY_underlying.parquet"
    spy_rows().to_parquet(options, index=False)
    pd.DataFrame({"date": ["2022-10-13", DAY], "close": [365.0, 357.5]}).to_parquet(
        underlying, index=False)
    return options, underlying


def test_reads_one_session_at_the_close_with_the_unadjusted_close_as_spot(archive):
    snapshot = load_spy_day(*archive, DAY, vix_close=31.94)

    assert snapshot.as_of == pd.Timestamp(f"{DAY} 16:00", tz="America/New_York")
    assert snapshot.spot == pytest.approx(357.5)
    assert snapshot.levels == {"SPY": 357.5, "^VIX": 31.94}
    assert (snapshot.quotes["bid"] != 99.0).all()
    assert set(snapshot.quotes["root"]) == {"SPY"}


def test_keeps_zero_bids_drops_zero_asks_and_maturities_beyond_a_year(archive):
    quotes = load_spy_day(*archive, DAY).quotes

    assert sorted(quotes["strike"]) == [350.0, 360.0, 360.0]
    assert quotes.loc[quotes["strike"] == 350.0, "bid"].item() == 0.0
    assert quotes["T"].max() <= 1.0


def test_settles_at_the_close_of_expiry_day(archive):
    quotes = load_spy_day(*archive, DAY).quotes
    friday = quotes.loc[quotes["expiry"] == "2022-10-21", "T"].iloc[0]

    assert friday * 365.0 == pytest.approx(7.0)


def test_every_quote_counts_as_fresh_since_the_archive_has_no_last_trade(archive):
    snapshot = load_spy_day(*archive, DAY)

    assert (pd.to_datetime(snapshot.quotes["lastTradeDate"], utc=True) == snapshot.as_of).all()


def test_refuses_a_session_absent_from_the_archive(archive):
    with pytest.raises(DataError, match="2022-10-12"):
        load_spy_day(*archive, "2022-10-12")
