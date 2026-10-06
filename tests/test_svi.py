import numpy as np
import pytest

from conftest import smile_table
from olab.errors import CalibrationError
from olab.surface.arbitrage import butterfly_violations, calendar_violations
from olab.surface.svi import (
    EssviSurface,
    SviSlice,
    essvi_total_variance,
    fit_errors,
    fit_essvi,
    fit_ssvi,
    fit_svi_slice,
    fit_svi_surface,
)

SHORT = SviSlice(a=0.002, b=0.05, rho=-0.6, m=0.01, sigma=0.08, maturity=0.1)
LONG = SviSlice(a=0.015, b=0.09, rho=-0.5, m=0.02, sigma=0.15, maturity=0.5)


def two_slices():
    return smile_table([(0.1, SHORT.total_variance), (0.5, LONG.total_variance)])


def test_raw_svi_is_recovered_from_its_own_smile():
    table = smile_table([(0.1, SHORT.total_variance)])
    fitted = fit_svi_slice(table)
    k = table["k"].to_numpy()
    np.testing.assert_allclose(fitted.implied_vol(k), SHORT.implied_vol(k), atol=1e-6)


def test_a_slice_needs_enough_quotes():
    with pytest.raises(CalibrationError, match="cannot pin"):
        fit_svi_slice(smile_table([(0.1, SHORT.total_variance)]).iloc[:5])


def test_penalised_fit_stays_above_the_previous_slice():
    surface = fit_svi_surface(two_slices(), constrained=True)
    assert calendar_violations([surface.slice(0.1), surface.slice(0.5)]) == 0


def test_surface_interpolates_total_variance_linearly_and_refuses_to_extrapolate():
    surface = fit_svi_surface(two_slices(), constrained=False)
    k = np.array([-0.1, 0.0, 0.1])
    middle = surface.slice(0.3)(k)
    near, far = surface.slices[0.1], surface.slices[0.5]
    np.testing.assert_allclose(middle, 0.5 * near.total_variance(k) + 0.5 * far.total_variance(k))
    np.testing.assert_allclose(surface.implied_vol(k, 0.3), np.sqrt(middle / 0.3))
    with pytest.raises(CalibrationError, match="extrapolate"):
        surface.slice(0.7)


def test_ssvi_is_arbitrage_free_by_construction():
    table = two_slices()
    atm = {0.1: float(SHORT.total_variance(0.0)), 0.5: float(LONG.total_variance(0.0))}
    ssvi = fit_ssvi(table, atm)
    assert ssvi.butterfly_bound <= 2.0 + 1e-9
    assert np.all(np.diff(ssvi.thetas) >= 0)
    assert butterfly_violations(ssvi.slice(0.3)) == 0
    with pytest.raises(CalibrationError, match="two maturities"):
        fit_ssvi(table.loc[table["T"] == 0.1], {0.1: atm[0.1]})
    with pytest.raises(CalibrationError, match="absent"):
        fit_ssvi(table, {0.1: atm[0.1], 0.3: atm[0.5]})
    with pytest.raises(CalibrationError, match="extrapolate"):
        ssvi.slice(1.0)


def test_essvi_wing_slopes_rebuild_the_ssvi_slice():
    k = np.linspace(-0.5, 0.5, 11)
    theta, psi, rho = 0.02, 0.3, -0.4
    a, b = psi * (1 + rho), psi * (1 - rho)
    x = psi / theta * k
    ssvi = 0.5 * theta * (1 + rho * x + np.sqrt((x + rho) ** 2 + 1 - rho**2))
    np.testing.assert_allclose(essvi_total_variance(k, theta, a, b), ssvi)


def test_essvi_chain_respects_its_constraints_between_and_on_pillars():
    table = two_slices()
    essvi = fit_essvi(table, fit_svi_surface(table, constrained=False))
    puts, calls = essvi.wings_put, essvi.wings_call
    assert np.all(np.diff(essvi.thetas) >= 0)
    assert np.all(np.diff(puts) >= 0) and np.all(np.diff(calls) >= 0)
    assert np.all((puts + calls) * np.maximum(puts, calls) <= 8 * essvi.thetas + 1e-12)
    slices = [essvi.slice(t) for t in np.linspace(0.1, 0.5, 9)]
    assert sum(butterfly_violations(s) for s in slices) == 0
    assert calendar_violations(slices) == 0
    assert np.all(np.abs(essvi.rhos) < 1)
    with pytest.raises(CalibrationError, match="extrapolate"):
        essvi.params_at(0.05)


def test_monotone_essvi_parameters_do_not_rule_out_calendar_arbitrage():
    # Same theta and call wing, steeper put wing: the slope at the money is (a - b) / 2,
    # so the later slice dips below the earlier one just right of the money. This is the
    # pattern the 2022 and SPY panels show between expiries one to three days apart.
    theta, a = 0.002, 0.05
    earlier = lambda k: essvi_total_variance(k, theta, a, 0.05)  # noqa: E731
    later = lambda k: essvi_total_variance(k, theta, a, 0.08)  # noqa: E731
    assert calendar_violations([earlier, later]) > 0


def test_essvi_fit_refuses_to_cross_where_the_quotes_do():
    # Quotes read off the crossing pair above: the fit must give up some accuracy rather
    # than reproduce the crossing, and the curvature psi / theta must not rise.
    theta, a = 0.002, 0.05
    table = smile_table([
        (15 / 365, lambda k: essvi_total_variance(k, theta, a, 0.05)),
        (16 / 365, lambda k: essvi_total_variance(k, theta, a, 0.08)),
    ])
    essvi = fit_essvi(table, fit_svi_surface(table, constrained=False))
    psi = 0.5 * (essvi.wings_call + essvi.wings_put)
    assert np.all(np.diff(psi / essvi.thetas) <= 1e-12)
    dense = [essvi.slice(t) for t in np.linspace(15 / 365, 16 / 365, 25)]
    assert calendar_violations(dense) == 0


def test_essvi_needs_two_maturities():
    table = smile_table([(0.1, SHORT.total_variance)])
    with pytest.raises(CalibrationError, match="two maturities"):
        fit_essvi(table, fit_svi_surface(table, constrained=False))


def test_essvi_surface_reads_atm_variance_off_theta():
    surface = EssviSurface(np.array([0.1, 0.2]), np.array([0.004, 0.008]),
                           np.array([0.1, 0.1]), np.array([0.05, 0.05]))
    assert surface.implied_vol(np.array([0.0]), 0.15)[0] == pytest.approx(0.2)


def test_fit_errors_report_vol_points_and_spread_capture():
    table = smile_table([(0.1, SHORT.total_variance)])
    model = table["iv"].to_numpy() + np.where(np.arange(len(table)) % 2, 0.01, 0.0)
    errors = fit_errors(table, model)
    assert errors["max_abs_vol_points"] == pytest.approx(1.0)
    assert errors["share_inside_spread"] == pytest.approx(0.5)
    assert errors["quotes"] == len(table)
