"""Assembly of the final HTML report.

Computes nothing: every number displayed here comes out of ``pipeline.py``. Nothing in the
page depends on the clock either, so the same captures always render the same bytes.
"""

from __future__ import annotations

import html as html_escape

from olab.pipeline import MODEL_NOTES, PremiumOutput, SurfaceOutput
from olab.report.charts import pnl_chart, premium_chart, smile_chart, term_chart
from olab.surface.arbitrage import K_GRID
from olab.surface.quotes import MAX_QUOTE_AGE_DAYS

TITLE = "SPX volatility surface and variance risk premium"
PANEL_SOURCE = "https://historicaldata.net/options.html"

STYLE = """
body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 0 auto;
       max-width: 1040px; padding: 2rem 1.25rem; color: #16181d; line-height: 1.5; }
h1 { font-size: 1.9rem; margin-bottom: 0.25rem; }
h2 { font-size: 1.25rem; margin-top: 2.5rem; border-bottom: 1px solid #e3e5ea;
     padding-bottom: 0.35rem; }
table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
th, td { text-align: right; padding: 0.45rem 0.6rem; border-bottom: 1px solid #eceef2; }
th:first-child, td:first-child { text-align: left; }
thead th { border-bottom: 2px solid #c9ccd4; }
.note { color: #5b6070; font-size: 0.9rem; }
.scroll { overflow-x: auto; }
svg { max-width: 100%; height: auto; }
"""


def _table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{html_escape.escape(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{html_escape.escape(cell)}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    table = f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
    return f'<div class="scroll">{table}</div>'


def _note(text: str) -> str:
    return f'<p class="note">{text}</p>'


def _num(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}"


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _vix_section(surface: SurfaceOutput) -> list[str]:
    cboe = surface.cboe
    rows = [["CBOE VIX, read at capture", _num(surface.snapshot.levels["^VIX"]), "published index"]]
    for label, term in (("near", cboe["near"]), ("next", cboe["next"])):
        rows.append([
            f"CBOE recipe, {label} term {term.expiry}",
            _num(100 * term.variance**0.5),
            f"{term.strikes_used} strikes, {term.lowest_strike:.0f} to {term.highest_strike:.0f}",
        ])
    rows.append(["CBOE recipe on this chain, 30 days", _num(cboe["vix"]), "interpolated"])
    return [
        "<h2>Reading the chain: the VIX, rebuilt</h2>",
        _note(
            "Before fitting anything, the white-paper recipe is run on the captured quotes: "
            "the two expiries bracketing thirty days, out-of-the-money strikes until two "
            "consecutive zero bids, the forward from the strike where calls and puts are "
            "closest, the rate from the chain's own put-call parity. Agreement with the "
            "published index is the check that strikes, expiries, settlement times and "
            "discounting are read correctly. The quotes are fifteen minutes delayed and the "
            "index is not, so the two are never read at quite the same instant."
        ),
        _table(["Source", "30-day vol", "Detail"], rows),
    ]


def _models_section(surface: SurfaceOutput) -> list[str]:
    rows = []
    for name, model in surface.models.items():
        errors, violations = model.errors, model.violations
        rows.append([
            name,
            _num(errors["rmse_vol_points"]),
            _num(errors["max_abs_vol_points"]),
            _pct(errors["share_inside_spread"]),
            f"{violations['butterfly_quoted']} / {violations['butterfly_extrapolated']}",
            f"{violations['calendar_quoted']} / {violations['calendar_extrapolated']}",
            _num(model.replicated_vix),
        ])
    notes = "".join(
        f"<li><strong>{html_escape.escape(n)}</strong>: {html_escape.escape(d)}</li>"
        for n, d in MODEL_NOTES.items()
    )
    quotes = surface.models[next(iter(surface.models))].errors["quotes"]
    dense = "; ".join(
        f"{html_escape.escape(name)}: {found['butterfly']:,} butterfly and "
        f"{found['calendar']:,} calendar points"
        for name, found in surface.between_pillars.items()
    )
    maturities = next(iter(surface.between_pillars.values()))["maturities"]
    return [
        "<h2>Fitting the surface: fit against arbitrage</h2>",
        f"<ul class='note'>{notes}</ul>",
        _table(
            ["Model", "RMSE (vol pts)", "Max miss", "Inside bid-ask",
             "Butterfly quoted / beyond", "Calendar quoted / beyond", "30-day replicated vol"],
            rows,
        ),
        _note(
            f"Errors over {quotes:,} out-of-the-money quotes. Arbitrage counts are grid points "
            f"on {len(K_GRID):,} log-moneyness values from {K_GRID[0]:.1f} to {K_GRID[-1]:.1f} "
            "per slice (butterfly: Durrleman's g negative; calendar: a later slice below an "
            "earlier one), split between the range where the expiry is quoted and the wings "
            "the model extrapolates. The 30-day vol is the continuous log-contract "
            "replication on each model's thirty-day slice; it reads the extrapolated wings, "
            "which is why the free fit, closest to the quotes, is furthest from the CBOE "
            f"recipe on the same chain. Between the fitted expiries, on {maturities:,} "
            f"interpolated maturities: {dense}."
        ),
        smile_chart(surface.quotes.table, surface.surfaces),
    ]


def _forwards_section(surface: SurfaceOutput) -> list[str]:
    rows = [
        [
            expiry,
            _num(fwd.maturity * 365, 1),
            _num(fwd.forward),
            _num(fwd.discount, 5),
            _pct(fwd.rate),
            str(fwd.pairs),
            str(fwd.trimmed),
            _num(fwd.residual, 3),
        ]
        for expiry, fwd in surface.quotes.forwards.items()
    ]
    return [
        "<h2>Forwards and discount factors from put-call parity</h2>",
        _note(
            "C - P = D (F - K) regressed on strikes within 5% of spot, after a Theil-Sen "
            "start and iterative trimming of pairs more than four robust deviations off the "
            "line. Inside three weeks the implied rate is noisy: a 0.1% error on D is a "
            "five-point error on the rate at one week, and a negligible one on the "
            "undiscounted premium."
        ),
        _table(
            ["Expiry", "Days", "Forward", "Discount", "Implied rate", "Pairs kept",
             "Pairs trimmed", "Residual (pts)"],
            rows,
        ),
    ]


def _chain_section(surface: SurfaceOutput) -> list[str]:
    rows = [
        [label, str(c["vertical"]), str(c["butterfly"]), str(c["checked_expiries"])]
        for label, c in surface.chain_arbitrage.items()
    ]
    refused = sorted(surface.quotes.refused.items(), key=lambda item: -item[1])
    return [
        "<h2>Executable arbitrage in the chain</h2>",
        _note(
            "A vertical or butterfly counts only if it makes money buying at the ask and "
            "selling at the bid. Nearly all of it comes from quotes whose last trade, and so "
            f"whose displayed bid and ask, is older than {MAX_QUOTE_AGE_DAYS:.0f} days."
        ),
        _table(["Quote set", "Vertical", "Butterfly", "Expiries"], rows),
        "<h2>What was set aside</h2>",
        _table(["Reason", "Quotes"], [[reason, f"{count:,}"] for reason, count in refused]),
    ]


def _premium_section(premium: PremiumOutput) -> list[str]:
    h = premium.headline
    start, end = premium.sample.index[0].date(), premium.sample.index[-1].date()
    headline = [
        ["Windows (21 trading days, non-overlapping)", str(h["windows"])],
        ["Mean VIX", _pct(h["mean_implied_vol"])],
        ["Mean realized vol", _pct(h["mean_realized_vol"])],
        ["Share of windows VIX above realized", _pct(h["share_implied_above_realized"])],
        ["Mean seller P&L (vol pts)", _num(h["mean_seller_pnl"])],
        ["Median seller P&L", _num(h["median_seller_pnl"])],
        ["Worst window", _num(h["worst_seller_pnl"])],
        ["Mean with 2.5x cap on realized", _num(h["mean_capped_seller_pnl"])],
        ["Annualised Sharpe", _num(h["annualised_sharpe"])],
        ["Skewness", _num(h["skewness"])],
    ]
    sens = premium.sensitivity
    spread = [
        [label, _num(sens[col].min()), _num(sens[col].median()), _num(sens[col].max())]
        for label, col in (("Mean seller P&L", "mean_seller_pnl"),
                           ("Annualised Sharpe", "annualised_sharpe"),
                           ("Worst window", "worst_seller_pnl"))
    ]
    reg = premium.regression
    regression = [
        ["alpha", _num(reg.alpha, 4), _num(reg.alpha_se, 4)],
        ["beta", _num(reg.beta, 3), _num(reg.beta_se, 3)],
        ["t-stat of beta = 1", _num(reg.t_beta_equals_one), ""],
        ["R squared", _num(reg.r_squared, 3), ""],
    ]
    regimes = [
        [str(label), str(int(row["windows"])), _num(row["mean_pnl"]), _num(row["worst_pnl"]),
         _pct(row["share_positive"])]
        for label, row in premium.regimes.iterrows()
    ]
    return [
        "<h2>The variance risk premium since 1990</h2>",
        _note(
            f"A thirty-day variance swap struck at the VIX close, {start} to {end}, settled "
            "on the next 21 trading days of S&amp;P 500 close-to-close returns. P&amp;L per "
            "unit of vega notional, (K&sup2; - RV) / 2K, in vol points."
        ),
        _table(["Statistic", "Value"], headline),
        premium_chart(premium.sample),
        pnl_chart(premium.sample),
        "<h3>How much the sampling phase matters</h3>",
        _note("The same statistics for each of the 21 possible starting days."),
        _table(["Statistic", "Min", "Median", "Max"], spread),
        "<h3>Is VIX squared an unbiased forecast of realized variance?</h3>",
        _note("Realized variance on VIX squared, non-overlapping windows, White standard errors."),
        _table(["Coefficient", "Estimate", "Std. error"], regression),
        "<h3>By VIX level at the strike date</h3>",
        _table(["Regime", "Windows", "Mean P&L", "Worst", "Share positive"], regimes),
    ]


def _panel_section(panel: dict) -> list[str]:
    rows = [
        [
            name,
            f"{_num(m['rmse_median'])} ({_num(m['rmse_low'])}–{_num(m['rmse_high'])})",
            _pct(m["inside_median"]),
            f"{int(m['sessions_with_quoted_butterfly'])} / {panel['sessions']}",
            f"{int(m['sessions_with_quoted_calendar'])} / {panel['sessions']}",
            f"{m['wings_median']:,.0f}",
            f"{m['replicated_minus_published_median']:+.2f}",
        ]
        for name, m in panel["models"].iterrows()
    ]
    low, high = panel["published_vix_range"]
    return [
        f"<h2>The same comparison on {panel['sessions']} sessions of 2022</h2>",
        _note(
            f"End-of-day SPX and SPXW chains from {panel['first']} to {panel['last']}, run "
            "through the same screen, fits and audits as the capture above; a median "
            f"session kept {panel['quotes_median']:,.0f} quotes over "
            f"{panel['expiries_median']:.0f} expiries. The published VIX ranged from "
            f"{low:.1f} to {high:.1f}: a bear market, not a calm one. Data: "
            f'<a href="{PANEL_SOURCE}">HistoricalData.net</a> free 2022H2 sample; its '
            "licence allows these aggregates and not the quotes, which are not "
            "redistributed here."
        ),
        _table(
            ["Model", "RMSE median (10–90%)", "Inside bid-ask, median",
             "Sessions with quoted butterfly", "Sessions with quoted calendar",
             "Wing violations, median", "30-day vol − VIX, median"],
            rows,
        ),
        _note(
            "The ranking by RMSE (free SVI, penalised SVI, eSSVI, SSVI) holds in "
            f"{_pct(panel['ranking_share'])} of sessions. The CBOE recipe on each close sits "
            f"{panel['recipe_gap_median']:+.2f} vol points from the published VIX at the "
            f"median ({panel['recipe_gap_low']:+.2f} to {panel['recipe_gap_high']:+.2f}, "
            "10th to 90th percentile); the index settles at 16:15 and the quotes are the "
            "ones standing at the close."
        ),
    ]


def build_report(
    surface: SurfaceOutput, premium: PremiumOutput, panel: dict | None = None
) -> str:
    """Render the whole report as one self-contained HTML document.

    ``panel`` is ``olab.panel.panel_summary`` of the multi-session run, when there is one.
    """
    snapshot = surface.snapshot
    sections = [
        f"<h1>{TITLE}</h1>",
        _note(
            f"Chain captured {snapshot.as_of:%Y-%m-%d %H:%M} UTC from 15-minute delayed "
            f"Yahoo quotes, SPX {snapshot.spot:,.2f}. Daily history from Yahoo closes."
        ),
        *_vix_section(surface),
        *_models_section(surface),
        "<h2>Term structure</h2>",
        term_chart(surface.quotes.table, surface.surfaces["SVI per slice"], snapshot.levels),
        *_forwards_section(surface),
        *_chain_section(surface),
        *([] if panel is None else _panel_section(panel)),
        *_premium_section(premium),
    ]
    body = "\n".join(sections)
    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        f"<title>{TITLE}</title>\n"
        f"<style>{STYLE}</style>\n</head>\n<body>\n{body}\n</body>\n</html>\n"
    )
