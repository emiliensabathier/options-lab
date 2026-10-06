"""Three ways to fit the smile: one SVI per slice, one SSVI surface, or chained eSSVI slices.

Raw SVI (Gatheral, 2004) gives each expiry five free parameters,

    w(k) = a + b (rho (k - m) + sqrt((k - m)^2 + sigma^2)),

and is what most open-source calibrators fit, slice by slice. It fits closely and promises
nothing: two neighbouring slices can cross (calendar arbitrage) and a single slice can imply
a negative density (butterfly arbitrage).

SSVI (Gatheral and Jacquier, 2014) ties every slice to its at-the-money total variance
``theta`` and shares three parameters across the whole surface,

    w(k, theta) = theta / 2 (1 + rho phi k + sqrt((phi k + rho)^2 + 1 - rho^2)),
    phi(theta)  = eta / (theta^gamma (1 + theta)^(1 - gamma)).

With ``theta`` non-decreasing in maturity, ``eta (1 + |rho|) <= 2`` and ``0 < gamma <= 1/2``,
they show the power-law surface is free of static arbitrage. Here those conditions are
imposed through the parametrisation, not checked afterwards: ``theta`` is a cumulative sum of
positive increments and ``eta`` is a fraction of its own upper bound. Whatever the optimiser
returns is arbitrage-free by construction, and ``arbitrage.py`` verifies it on a grid anyway.

The power-law surface is rigid: three numbers set the skew of every expiry, and on an index
whose one-week skew is several times steeper than its one-year skew it cannot fit both.
eSSVI (Hendriks and Martini, 2019; Corbetta et al., 2019) keeps the SSVI shape per slice but
lets each expiry carry its own ``(theta, psi = theta phi, rho)``. Writing the two wing slopes
``a = psi (1 + rho)`` and ``b = psi (1 - rho)`` (twice the asymptotic ``dw/d|k|`` on each
side) makes the constraints linear or nearly so:

- butterfly, per slice: ``max(a, b) < 4`` and ``(a + b) max(a, b) <= 8 theta``, which is
  Gatheral and Jacquier's sufficient condition ``theta phi (1 + |rho|) < 4``,
  ``theta phi^2 (1 + |rho|) <= 4`` rewritten in these coordinates;
- calendar, between consecutive slices: ``theta``, ``a`` and ``b`` all non-decreasing, and
  ``psi / theta`` non-increasing. The first three are Hendriks and Martini's necessary
  conditions and are not enough on their own: with ``theta`` and ``a`` flat and ``b``
  rising, the slope at the money, ``(a - b) / 2``, falls and the later slice dips below the
  earlier one. The fourth makes them sufficient (see ``_fit_essvi_slice``).

Slices are fitted in maturity order, each bounded by the one before. Linear interpolation of
``theta``, ``a`` and ``b`` is linear interpolation of ``theta``, ``psi`` and ``rho psi``,
the scheme Corbetta et al. (2019, section 5) and Mingone (2022, section 5.1) prove
arbitrage-free between calibrated slices: ``psi / theta`` is a ratio of two linear functions
of time, so it stays monotone between pillars, and the butterfly constraint is convex along
any segment on which ``a`` and ``b`` both increase.

All fits minimise implied-volatility error scaled by each quote's half bid-ask spread in
volatility terms, so a miss inside the spread costs less than one outside it. Starts come
from a fixed grid, not a random draw, so the published surface is reproducible bit for bit.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product

import numpy as np
import pandas as pd
from scipy.optimize import least_squares

from olab.errors import CalibrationError
from olab.surface.arbitrage import durrleman_g as _durrleman_g

MIN_HALF_SPREAD = 0.0025  # vol floor on the residual scale: 25 bp, so no quote dominates
MIN_QUOTES_PER_SLICE = 8
EPS = 1e-6
PENALTY = 1e3
PENALTY_GRID = np.linspace(-0.6, 0.6, 121)


def _scale(quotes: pd.DataFrame) -> np.ndarray:
    half = 0.5 * (quotes["iv_ask"] - quotes["iv_bid"]).to_numpy()
    return np.maximum(half, MIN_HALF_SPREAD)


# --- raw SVI, per slice --------------------------------------------------------------------


@dataclass(frozen=True)
class SviSlice:
    a: float
    b: float
    rho: float
    m: float
    sigma: float
    maturity: float

    def total_variance(self, k):
        k = np.asarray(k, dtype=float)
        x = k - self.m
        return self.a + self.b * (self.rho * x + np.sqrt(x * x + self.sigma**2))

    def implied_vol(self, k):
        return np.sqrt(np.maximum(self.total_variance(k), 0.0) / self.maturity)


def _quasi_explicit_start(k, w, weight, maturity) -> np.ndarray:
    """Best raw SVI over a grid of ``(m, sigma)``, the other three solved linearly.

    For fixed ``m`` and ``sigma``, ``w = a + d y + c sqrt(y^2 + 1)`` with ``y = (k - m) /
    sigma`` is linear in ``(a, d, c)`` (Zeliade, 2009). A 2-D grid search with a 3-column
    least squares inside replaces a blind multi-start of the 5-D problem.
    """
    best, best_cost = None, np.inf
    for m, sigma in product(np.linspace(-0.2, 0.2, 21), np.geomspace(0.005, 1.0, 21)):
        y = (k - m) / sigma
        design = np.column_stack([np.ones_like(y), y, np.sqrt(y * y + 1)]) * weight[:, None]
        (a, d, c), *_ = np.linalg.lstsq(design, w * weight, rcond=None)
        if c <= 0 or abs(d) >= c:
            continue
        cost = float(np.sum((design @ [a, d, c] - w * weight) ** 2))
        if cost < best_cost:
            b, rho = c / sigma, d / c
            best, best_cost = np.array([a, b, rho, m, sigma]), cost
    if best is None:
        w_atm = float(np.interp(0.0, k, w))
        best = np.array([0.5 * w_atm, w_atm / 0.1, -0.5, 0.0, 0.1])
    return best


def fit_svi_slice(
    quotes: pd.DataFrame, previous: SviSlice | None = None, constrained: bool = False
) -> SviSlice:
    """Least-squares raw SVI on one expiry, in volatility space, scaled by the spread.

    ``constrained=True`` adds penalties for a negative Durrleman ``g`` on ``PENALTY_GRID``
    and, if ``previous`` is given, for crossing below the previous slice on it: the
    approach of the open-source SVI calibrators, run on the whole moneyness grid rather
    than only where quotes exist, because that is where unconstrained short-dated slices
    break.
    """
    if len(quotes) < MIN_QUOTES_PER_SLICE:
        raise CalibrationError(f"{len(quotes)} quotes cannot pin five SVI parameters")
    maturity = float(quotes["T"].iloc[0])
    k = quotes["k"].to_numpy()
    iv = quotes["iv"].to_numpy()
    scale = _scale(quotes)
    # a vol miss of scale costs about 2 sigma T scale in total variance
    x0 = _quasi_explicit_start(k, iv**2 * maturity, 1.0 / (2 * iv * maturity * scale), maturity)
    floor = previous.total_variance(PENALTY_GRID) if previous is not None else None

    def residual(p, weight=PENALTY):
        a, b, rho, m, sigma = p
        x = k - m
        w = a + b * (rho * x + np.sqrt(x * x + sigma**2))
        fit = (np.sqrt(np.maximum(w, EPS * maturity) / maturity) - iv) / scale
        if not constrained:
            return fit
        candidate = SviSlice(a, b, rho, m, sigma, maturity)
        g = _durrleman_g(candidate.total_variance, PENALTY_GRID)
        parts = [fit, weight * np.maximum(-g, 0.0)]
        if floor is not None:
            gap = floor - candidate.total_variance(PENALTY_GRID)
            parts.append(weight * np.maximum(gap, 0.0) / maturity)
        return np.concatenate(parts)

    lower = np.array([-1.0, 0.0, -1.0 + EPS, -1.0, 1e-4])
    upper = np.array([1.0, 5.0, 1.0 - EPS, 1.0, 2.0])
    starts = [np.clip(x0, lower + EPS, upper - EPS)]
    if constrained and previous is not None:
        # The previous slice lifted to this expiry's at-the-money variance cannot cross it
        # and is a feasible place to start when the free fit lands deep in a penalty.
        lift = max(float(np.interp(0.0, k, iv**2 * maturity) - previous.total_variance(0.0)), 0)
        prev = [previous.a + lift, previous.b, previous.rho, previous.m, previous.sigma]
        starts.append(np.clip(prev, lower + EPS, upper - EPS))
    best = None
    for start in starts:
        x = start
        # continuation: tighten the penalty in steps so the optimiser is led to the
        # feasible region instead of being walled off from it
        for weight in (PENALTY / 100, PENALTY / 10, PENALTY) if constrained else (PENALTY,):
            x = least_squares(residual, x, bounds=(lower, upper), method="trf", args=(weight,)).x
        cost = float(np.sum(residual(x) ** 2))
        if best is None or cost < best[0]:
            best = (cost, x)
    a, b, rho, m, sigma = best[1]
    return SviSlice(a, b, rho, m, sigma, maturity)


@dataclass(frozen=True)
class SviSurface:
    """Raw SVI slices on their pillars; total variance is linear in time between them."""

    slices: dict[float, SviSlice]

    @property
    def maturities(self) -> np.ndarray:
        return np.array(sorted(self.slices))

    def slice(self, maturity: float):
        pillars = self.maturities
        if not pillars[0] <= maturity <= pillars[-1]:
            raise CalibrationError(
                f"maturity {maturity:.4f} is outside the calibrated pillars; refusing to "
                "extrapolate"
            )
        upper = int(np.searchsorted(pillars, maturity))
        if pillars[upper] == maturity:
            return self.slices[float(pillars[upper])].total_variance
        t0, t1 = pillars[upper - 1], pillars[upper]
        near, far = self.slices[float(t0)], self.slices[float(t1)]
        weight = (maturity - t0) / (t1 - t0)
        return lambda k: (1 - weight) * near.total_variance(k) + weight * far.total_variance(k)

    def implied_vol(self, k, maturity: float):
        return np.sqrt(np.maximum(self.slice(maturity)(k), 0.0) / maturity)


def fit_svi_surface(quotes: pd.DataFrame, constrained: bool) -> SviSurface:
    """One raw SVI per expiry; constrained slices are fitted in maturity order."""
    slices: dict[float, SviSlice] = {}
    previous = None
    for maturity, group in quotes.groupby("T", sort=True):
        fitted = fit_svi_slice(group, previous if constrained else None, constrained)
        slices[float(maturity)] = fitted
        previous = fitted
    return SviSurface(slices)


# --- SSVI, whole surface -------------------------------------------------------------------


@dataclass(frozen=True)
class SsviSurface:
    """A calibrated SSVI surface on its pillar maturities."""

    maturities: np.ndarray
    thetas: np.ndarray
    rho: float
    eta: float
    gamma: float

    def phi(self, theta):
        theta = np.asarray(theta, dtype=float)
        return self.eta / (theta**self.gamma * (1.0 + theta) ** (1.0 - self.gamma))

    def theta_at(self, maturity: float) -> float:
        """ATM total variance at any maturity inside the pillars, linear in time.

        Linear interpolation of a non-decreasing sequence is non-decreasing, so the
        interpolated slice inherits the surface's freedom from calendar arbitrage.
        """
        if not self.maturities[0] <= maturity <= self.maturities[-1]:
            raise CalibrationError(
                f"maturity {maturity:.4f} is outside the calibrated pillars "
                f"[{self.maturities[0]:.4f}, {self.maturities[-1]:.4f}]; refusing to "
                "extrapolate"
            )
        return float(np.interp(maturity, self.maturities, self.thetas))

    def total_variance(self, k, theta):
        k = np.asarray(k, dtype=float)
        p = self.phi(theta) * k
        return 0.5 * theta * (1 + self.rho * p + np.sqrt((p + self.rho) ** 2 + 1 - self.rho**2))

    def slice(self, maturity: float):
        """Total variance as a function of log-moneyness at one maturity."""
        theta = self.theta_at(maturity)
        return lambda k: self.total_variance(k, theta)

    def implied_vol(self, k, maturity: float):
        return np.sqrt(self.slice(maturity)(k) / maturity)

    @property
    def butterfly_bound(self) -> float:
        """``eta (1 + |rho|)``, which the power-law no-arbitrage condition needs at or below 2."""
        return self.eta * (1.0 + abs(self.rho))


def _unpack(p: np.ndarray, n: int) -> tuple[np.ndarray, float, float, float]:
    thetas = np.cumsum(np.exp(p[:n]))
    rho, gamma, share = p[n], p[n + 1], p[n + 2]
    eta = share * 2.0 / (1.0 + abs(rho))
    return thetas, rho, eta, gamma


def fit_ssvi(quotes: pd.DataFrame, atm_guess: dict[float, float]) -> SsviSurface:
    """Joint least squares over every slice's ``theta`` and the three shared parameters.

    ``atm_guess`` maps maturity to a starting ATM total variance, typically read off the
    per-slice SVI fits; it is made non-decreasing before use.
    """
    maturities = np.array(sorted(atm_guess))
    if len(maturities) < 2:
        raise CalibrationError("a surface needs at least two maturities")
    n = len(maturities)
    index = {t: i for i, t in enumerate(maturities)}
    slice_of = quotes["T"].map(index).to_numpy()
    if np.isnan(slice_of.astype(float)).any():
        raise CalibrationError("quotes carry maturities absent from the ATM guesses")
    k = quotes["k"].to_numpy()
    iv = quotes["iv"].to_numpy()
    t = quotes["T"].to_numpy()
    scale = _scale(quotes)

    guess = np.maximum.accumulate([max(atm_guess[m], 1e-6) for m in maturities])
    increments = np.diff(np.concatenate([[0.0], guess]))
    log_inc0 = np.log(np.maximum(increments, 1e-7))

    def residual(p):
        thetas, rho, eta, gamma = _unpack(p, n)
        theta = thetas[slice_of]
        phi = eta / (theta**gamma * (1.0 + theta) ** (1.0 - gamma))
        x = phi * k
        w = 0.5 * theta * (1 + rho * x + np.sqrt((x + rho) ** 2 + 1 - rho**2))
        return (np.sqrt(w / t) - iv) / scale

    lower = np.concatenate([np.full(n, -30.0), [-1.0 + EPS, EPS, EPS]])
    upper = np.concatenate([np.full(n, 5.0), [1.0 - EPS, 0.5, 1.0]])
    best = None
    for rho0, gamma0, share0 in product((-0.8, -0.5, -0.2), (0.25, 0.45), (0.3, 0.8)):
        x0 = np.concatenate([log_inc0, [rho0, gamma0, share0]])
        fit = least_squares(residual, x0, bounds=(lower, upper), method="trf")
        if best is None or fit.cost < best.cost:
            best = fit
    if not best.success:
        raise CalibrationError(f"SSVI least squares did not converge: {best.message}")
    thetas, rho, eta, gamma = _unpack(best.x, n)
    return SsviSurface(maturities=maturities, thetas=thetas, rho=rho, eta=eta, gamma=gamma)


# --- eSSVI, chained slices -------------------------------------------------------------------

WING_LIMIT = 4.0 - 1e-6


def essvi_total_variance(k, theta: float, a: float, b: float):
    """SSVI slice in wing-slope coordinates: ``psi = (a + b) / 2``, ``rho = (a - b) / (a + b)``."""
    k = np.asarray(k, dtype=float)
    psi = 0.5 * (a + b)
    rho = (a - b) / (a + b)
    x = psi / theta * k
    return 0.5 * theta * (1 + rho * x + np.sqrt((x + rho) ** 2 + 1 - rho**2))


def _butterfly_floor(a: float, b: float) -> float:
    """Smallest ``theta`` the butterfly condition allows for given wing slopes."""
    return (a + b) * max(a, b) / 8.0


@dataclass(frozen=True)
class EssviSurface:
    """Chained eSSVI slices on pillar maturities, interpolated linearly in time."""

    maturities: np.ndarray
    thetas: np.ndarray
    wings_put: np.ndarray  # b = psi (1 - rho), the left wing
    wings_call: np.ndarray  # a = psi (1 + rho), the right wing

    @property
    def rhos(self) -> np.ndarray:
        return (self.wings_call - self.wings_put) / (self.wings_call + self.wings_put)

    def params_at(self, maturity: float) -> tuple[float, float, float]:
        if not self.maturities[0] <= maturity <= self.maturities[-1]:
            raise CalibrationError(
                f"maturity {maturity:.4f} is outside the calibrated pillars; refusing to "
                "extrapolate"
            )
        return tuple(
            float(np.interp(maturity, self.maturities, series))
            for series in (self.thetas, self.wings_call, self.wings_put)
        )

    def slice(self, maturity: float):
        theta, a, b = self.params_at(maturity)
        return lambda k: essvi_total_variance(k, theta, a, b)

    def implied_vol(self, k, maturity: float):
        return np.sqrt(self.slice(maturity)(k) / maturity)


def _fit_essvi_slice(quotes, floor: tuple[float, float, float], starts) -> tuple:
    """Fit one slice inside the calendar bounds set by the previous one, ``floor``.

    No calendar spread between slices ``(theta1, rho1, psi1)`` and ``(theta2, rho2, psi2)``:
    Hendriks and Martini (2019, Proposition 3.5), as restated by Mingone (2022, "No arbitrage
    global parametrization for the eSSVI volatility surface", arXiv:2204.00312, section 2.1):

    - necessary: ``theta2 > theta1`` and ``psi2 max((1+rho1)/(1+rho2), (1-rho1)/(1-rho2)) >= psi1``,
      that is ``a2 >= a1`` and ``b2 >= b1``;
    - sufficient: the necessary conditions and ``psi2 <= psi1 theta2 / theta1``, or
      ``(rho1 - psi2 rho2 / psi1)^2 <= (theta2/theta1 - 1)(psi2^2 theta1 / (psi1^2 theta2) - 1)``.

    The first sufficient branch is imposed, as Mingone does, because it is a floor on
    ``theta``: ``theta >= psi / phi_prev`` with ``phi_prev = psi1 / theta1``. The second
    branch, which admits a rising ``psi / theta``, is not used, so the domain searched is a
    subset of the arbitrage-free one. Hendriks and Martini's paper itself was not available
    to check; the statement is Mingone's, whose proof of section 5.1 uses the first branch in
    the form ``psi_u theta_t - psi_t theta_u <= 0``. Corbetta et al. (2019, section 2.2) give
    the necessary conditions alone as necessary and sufficient; the counterexample in
    ``tests/test_svi.py`` satisfies them and crosses.
    """
    maturity = float(quotes["T"].iloc[0])
    k = quotes["k"].to_numpy()
    iv = quotes["iv"].to_numpy()
    scale = _scale(quotes)
    theta_prev, a_prev, b_prev = floor
    curvature_prev = 0.5 * (a_prev + b_prev) / theta_prev if theta_prev > 0 else np.inf

    def theta_floor(a, b):
        return max(theta_prev, _butterfly_floor(a, b), 0.5 * (a + b) / curvature_prev)

    def unpack(p):
        a, b, slack = p
        return theta_floor(a, b) + slack, a, b

    def residual(p):
        theta, a, b = unpack(p)
        w = essvi_total_variance(k, theta, a, b)
        return (np.sqrt(w / maturity) - iv) / scale

    lower = [max(a_prev, EPS), max(b_prev, EPS), 0.0]
    upper = [WING_LIMIT, WING_LIMIT, 1.0]
    best = None
    for theta0, a0, b0 in starts:
        a0 = float(np.clip(a0, lower[0], upper[0] - EPS))
        b0 = float(np.clip(b0, lower[1], upper[1] - EPS))
        slack0 = max(theta0 - theta_floor(a0, b0), 0.0)
        fit = least_squares(residual, [a0, b0, slack0], bounds=(lower, upper), method="trf")
        if best is None or fit.cost < best.cost:
            best = fit
    return unpack(best.x)


def fit_essvi(quotes: pd.DataFrame, svi: SviSurface) -> EssviSurface:
    """Fit eSSVI slice by slice in maturity order, each constrained by the one before.

    ``svi`` supplies starting points: the raw SVI at-the-money variance and wing slopes
    ``2 b (1 +/- rho)`` of the same expiry.
    """
    maturities = svi.maturities
    if len(maturities) < 2:
        raise CalibrationError("a surface needs at least two maturities")
    floor = (0.0, 0.0, 0.0)
    params = []
    for maturity in maturities:
        start = svi.slices[float(maturity)]
        theta0 = float(start.total_variance(0.0))
        a0, b0 = 2 * start.b * (1 + start.rho), 2 * start.b * (1 - start.rho)
        starts = [(theta0, a0, b0), (theta0, 0.5 * a0, 0.5 * b0), (theta0, floor[1], floor[2])]
        floor = _fit_essvi_slice(quotes.loc[quotes["T"] == maturity], floor, starts)
        params.append(floor)
    thetas, calls, puts = (np.array(column) for column in zip(*params, strict=True))
    return EssviSurface(maturities=maturities, thetas=thetas, wings_put=puts, wings_call=calls)


def fit_errors(quotes: pd.DataFrame, model_iv: np.ndarray) -> dict[str, float]:
    """How far a fit sits from the market, in the two units a trader reads."""
    miss = model_iv - quotes["iv"].to_numpy()
    inside = (model_iv >= quotes["iv_bid"].to_numpy()) & (model_iv <= quotes["iv_ask"].to_numpy())
    return {
        "rmse_vol_points": float(np.sqrt(np.mean(miss**2)) * 100),
        "max_abs_vol_points": float(np.max(np.abs(miss)) * 100),
        "share_inside_spread": float(inside.mean()),
        "quotes": int(len(miss)),
    }
