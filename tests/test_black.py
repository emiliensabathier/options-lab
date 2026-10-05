import numpy as np
import pytest

from olab.black import black_price, black_vega, implied_vol, normalised_otm_price


def test_put_call_parity_holds_on_undiscounted_prices():
    call = black_price(100.0, 90.0, 0.5, 0.25, True)
    put = black_price(100.0, 90.0, 0.5, 0.25, False)
    assert float(call - put) == pytest.approx(10.0, abs=1e-10)


@pytest.mark.parametrize("strike", [50.0, 95.0, 100.0, 105.0, 200.0])
@pytest.mark.parametrize("is_call", [True, False])
def test_implied_vol_inverts_black_to_machine_precision(strike, is_call):
    price = float(black_price(100.0, strike, 0.3, 0.35, is_call))
    sigma, reason = implied_vol(price, 100.0, strike, 0.3, is_call)
    assert reason is None
    assert sigma == pytest.approx(0.35, rel=1e-10)


def test_implied_vol_names_why_a_price_has_no_volatility():
    assert implied_vol(0.0, 100.0, 100.0, 0.25, True) == (None, "non_positive_price")
    assert implied_vol(5.0, 100.0, 90.0, 0.25, True) == (None, "below_intrinsic")
    assert implied_vol(150.0, 100.0, 90.0, 0.25, True) == (None, "above_maximum")


def test_vega_matches_a_finite_difference():
    bump = 1e-6
    numeric = (black_price(100, 110, 0.5, 0.2 + bump, True)
               - black_price(100, 110, 0.5, 0.2 - bump, True)) / (2 * bump)
    assert float(black_vega(100, 110, 0.5, 0.2)) == pytest.approx(float(numeric), rel=1e-6)


def test_normalised_price_is_the_out_of_the_money_premium_per_unit_forward():
    k = np.array([-0.2, 0.0, 0.15])
    w = 0.04 * 0.5
    strikes = 100.0 * np.exp(k)
    expected = np.where(k >= 0, black_price(100, strikes, 0.5, 0.2, True),
                        black_price(100, strikes, 0.5, 0.2, False)) / 100.0
    np.testing.assert_allclose(normalised_otm_price(k, w), expected, rtol=1e-12)
