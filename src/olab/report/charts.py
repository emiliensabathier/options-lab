"""Chart rendering to inline SVG.

Charts are embedded directly in the HTML so the report opens offline. The SVG output is
made deterministic (fixed hash salt, no timestamp) so that re-rendering the same data
yields the same bytes and a committed report can be checked against a fresh one.
"""

from __future__ import annotations

import io

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
matplotlib.rcParams["svg.hashsalt"] = "olab"
from matplotlib.figure import Figure  # noqa: E402

FIGSIZE = (9.0, 4.0)
DPI = 110
SMILE_DAYS = (7, 30, 180)  # expiries shown on the smile chart: the nearest listed to each
EXTRAPOLATION = 0.1  # log-moneyness drawn beyond the last quote on each side


def figure_to_svg(fig: Figure) -> str:
    """Serialize a figure as inline SVG markup, stripped of its XML preamble."""
    buffer = io.StringIO()
    fig.savefig(buffer, format="svg", bbox_inches="tight", metadata={"Date": None})
    markup = buffer.getvalue()
    return markup[markup.index("<svg") :]


def _axes(fig: Figure, position, title: str, xlabel: str, ylabel: str):
    axes = fig.add_subplot(*position)
    axes.set_title(title, fontsize="medium")
    axes.set_xlabel(xlabel)
    axes.set_ylabel(ylabel)
    axes.grid(True, alpha=0.25)
    return axes


def _nearest_expiries(table: pd.DataFrame, days: tuple[int, ...]) -> list[float]:
    maturities = np.array(sorted(table["T"].unique()))
    return [float(maturities[np.abs(maturities * 365 - d).argmin()]) for d in days]


def smile_figure(table: pd.DataFrame, surfaces: dict[str, object]) -> Figure:
    """Market bid-ask against two fits, for a short, a one-month and a six-month expiry.

    Each fitted curve runs a little past the last quote, which is where the free SVI and
    the arbitrage-free fits part ways. Returned as a figure because the README needs the
    same picture as a raster.
    """
    fig = Figure(figsize=(11.0, 3.8), dpi=DPI)
    for position, maturity in enumerate(_nearest_expiries(table, SMILE_DAYS), start=1):
        quotes = table.loc[table["T"] == maturity]
        axes = _axes(fig, (1, len(SMILE_DAYS), position),
                     f"{quotes['expiry'].iloc[0]} ({maturity * 365:.0f} days)",
                     "log-moneyness ln(K/F)", "implied vol (%)" if position == 1 else "")
        axes.vlines(quotes["k"], 100 * quotes["iv_bid"], 100 * quotes["iv_ask"],
                    color="#4b5161", linewidth=2.0, label="market bid-ask")
        k = np.linspace(quotes["k"].min() - EXTRAPOLATION, quotes["k"].max() + EXTRAPOLATION, 300)
        for name, style in (("SVI per slice", "-"), ("eSSVI", "--")):
            axes.plot(k, 100 * surfaces[name].implied_vol(k, maturity), style, linewidth=1.3,
                      label=name)
        if position == 1:
            axes.legend(frameon=False, fontsize="small")
    fig.tight_layout()
    return fig


def smile_chart(table: pd.DataFrame, surfaces: dict[str, object]) -> str:
    return figure_to_svg(smile_figure(table, surfaces))


def term_chart(table: pd.DataFrame, svi, levels: dict[str, float]) -> str:
    """At-the-money volatility by expiry, with the CBOE's 9-day, 30-day and 3-month indices."""
    fig = Figure(figsize=FIGSIZE, dpi=DPI)
    axes = _axes(fig, (1, 1, 1), "At-the-money term structure", "days to expiry", "vol (%)")
    maturities = np.array(sorted(table["T"].unique()))
    atm = [100 * float(svi.implied_vol(np.array([0.0]), t)[0]) for t in maturities]
    axes.plot(maturities * 365, atm, "o-", markersize=3, linewidth=1.2,
              label="SVI at the forward")
    for symbol, days in (("^VIX9D", 9), ("^VIX", 30), ("^VIX3M", 93)):
        if symbol in levels:
            axes.plot(days, levels[symbol], "s", color="#c0392b")
            axes.annotate(symbol.lstrip("^"), (days, levels[symbol]),
                          textcoords="offset points", xytext=(6, -12), fontsize="small")
    axes.legend(frameon=False, loc="lower right")
    return figure_to_svg(fig)


def premium_chart(sample: pd.DataFrame) -> str:
    """VIX at each strike date against the volatility the next 21 trading days delivered."""
    fig = Figure(figsize=FIGSIZE, dpi=DPI)
    axes = _axes(fig, (1, 1, 1), "VIX against subsequent realized volatility (non-overlapping)",
                 "", "vol (%)")
    axes.plot(sample.index, 100 * sample["implied_vol"], linewidth=1.0, label="VIX")
    axes.plot(sample.index, 100 * sample["realized_vol"], linewidth=1.0,
              label="realized, next 21 days")
    axes.legend(frameon=False, loc="upper left")
    return figure_to_svg(fig)


def pnl_chart(sample: pd.DataFrame) -> str:
    """Distribution of the variance seller's take, in vol points per unit of vega."""
    fig = Figure(figsize=FIGSIZE, dpi=DPI)
    axes = _axes(fig, (1, 1, 1), "Seller P&L per window (vol points of vega notional)",
                 "vol points", "windows")
    axes.hist(sample["seller_pnl_vol_points"], bins=60, color="#4a6fa5")
    axes.axvline(0.0, color="#16181d", linewidth=0.8)
    return figure_to_svg(fig)
