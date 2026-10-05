"""Exception types shared across the package."""


class DataError(Exception):
    """Raised when a captured input is missing, malformed or unusable.

    Never caught internally to substitute a default: a quote that is filled in becomes an
    implied volatility nobody quoted.
    """


class CalibrationError(Exception):
    """Raised when a fit cannot produce a surface that passes its own checks.

    A calibration that converges to an arbitrageable surface is a failure, not a result.
    """
