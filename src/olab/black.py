"""Black-76 on the forward, and its inversion.

Prices here are undiscounted: a quoted premium divided by the discount factor the chain
itself implies through put-call parity. Working on the forward removes any assumption about
the dividend yield or the funding rate.

Inversion is delegated to Peter Jaeckel's "Let's Be Rational" (2015) through the MIT-licensed
``py_lets_be_rational``: a fixed two-step Householder scheme that reaches machine precision
from a rational initial guess, for any strike and maturity. That replaces the Newton-plus-
bisection loop most open-source pricers use, which needs a starting point, a tolerance and
an iteration cap, and which fails silently on deep out-of-the-money wings where vega
vanishes.
"""

from __future__ import annotations

import numpy as np
import py_lets_be_rational as lbr
from py_lets_be_rational.exceptions import AboveMaximumException, BelowIntrinsicException
from scipy.stats import norm

# Depending on the path taken, the library signals an unattainable price either with these
# sentinels or by raising; both are mapped to the same named reasons.
BELOW_INTRINSIC = lbr.constants.VOLATILITY_VALUE_TO_SIGNAL_PRICE_IS_BELOW_INTRINSIC
ABOVE_MAXIMUM = lbr.constants.VOLATILITY_VALUE_TO_SIGNAL_PRICE_IS_ABOVE_MAXIMUM


def black_price(forward, strike, maturity, sigma, is_call):
    """Undiscounted Black-76 premium. Vectorised over every argument."""
    forward, strike, maturity, sigma = np.broadcast_arrays(
        *(np.asarray(x, dtype=float) for x in (forward, strike, maturity, sigma))
    )
    stdev = sigma * np.sqrt(maturity)
    d1 = np.log(forward / strike) / stdev + 0.5 * stdev
    d2 = d1 - stdev
    call = forward * norm.cdf(d1) - strike * norm.cdf(d2)
    put = call - (forward - strike)
    return np.where(is_call, call, put)


def black_vega(forward, strike, maturity, sigma):
    """Undiscounted sensitivity of the premium to sigma."""
    stdev = np.asarray(sigma) * np.sqrt(maturity)
    d1 = np.log(np.asarray(forward) / strike) / stdev + 0.5 * stdev
    return np.asarray(forward) * norm.pdf(d1) * np.sqrt(maturity)


def normalised_otm_price(k, total_variance):
    """Out-of-the-money Black premium per unit of forward, as a function of log-moneyness.

    A put below the forward, a call above it. Expressed this way the price depends on
    ``k = ln(K/F)`` and ``w = sigma^2 T`` alone, which is what the replication integral and
    the SVI family are both written in.
    """
    k = np.asarray(k, dtype=float)
    root = np.sqrt(np.asarray(total_variance, dtype=float))
    d1 = -k / root + 0.5 * root
    d2 = d1 - root
    call = norm.cdf(d1) - np.exp(k) * norm.cdf(d2)
    put = call - (1.0 - np.exp(k))
    return np.where(k >= 0.0, call, put)


def implied_vol(price: float, forward: float, strike: float, maturity: float, is_call: bool):
    """Black volatility of an undiscounted premium, or ``None`` with the reason it has none.

    Returns ``(sigma, None)`` on success and ``(None, reason)`` when the premium sits outside
    the no-arbitrage band ``[intrinsic, upper bound]``. No volatility is invented for a price
    that cannot have one.
    """
    if price <= 0.0:
        return None, "non_positive_price"
    flag = 1.0 if is_call else -1.0
    try:
        sigma = lbr.implied_volatility_from_a_transformed_rational_guess(
            price, forward, strike, maturity, flag
        )
    except BelowIntrinsicException:
        return None, "below_intrinsic"
    except AboveMaximumException:
        return None, "above_maximum"
    if not np.isfinite(sigma):
        return None, "no_solution"
    if sigma == BELOW_INTRINSIC or sigma <= 0.0:
        return None, "below_intrinsic"
    if sigma == ABOVE_MAXIMUM:
        return None, "above_maximum"
    return float(sigma), None
