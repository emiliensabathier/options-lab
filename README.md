# options-lab

What S&P 500 implied volatility prices: an arbitrage-free surface fitted to a real SPX
chain, and the premium a seller of that volatility has collected since 1990.

![ci](https://github.com/emiliensabathier/options-lab/actions/workflows/ci.yml/badge.svg)

## Results

### The surface: closeness to quotes against freedom from arbitrage

One SPX chain captured 2026-10-05 16:09 UTC (15-minute delayed quotes, index at 7,761.75),
42 expiries fitted from one week to just over a year (a 43rd is refused: too few
put-call pairs to pin its forward), 7,425 out-of-the-money quotes after screening. Four models were fitted to the same quotes and audited the same way.

| Model | RMSE (vol pts) | Inside bid-ask | Butterfly arbitrage, quoted / wings | Calendar arbitrage, quoted / wings | 30-day replicated vol |
| --- | --- | --- | --- | --- | --- |
| SVI per slice | 0.13 | 30.0% | 0 / 8,393 | 12 / 8,676 | 16.03 |
| SVI + penalties | 0.60 | 25.1% | 0 / 618 | 596 / 2,982 | 15.29 |
| SSVI | 2.02 | 3.2% | 0 / 0 | 0 / 0 | 15.08 |
| eSSVI | 1.87 | 2.5% | 0 / 0 | 0 / 0 | 15.00 |

Arbitrage counts are grid points out of 1,201 per slice on log-moneyness -0.6 to 0.6:
Durrleman's *g* negative for butterfly, a later slice below an earlier one for calendar.
They are split between the strikes each expiry is quoted at and the wings the model
extrapolates. The CBOE white-paper recipe run on the same chain gives **15.31** against a
published VIX of **15.57**.

There is no free lunch here, and the table says where it is paid for. Five free
parameters per expiry fit the surface to an overall RMSE of 0.13 vol points (0.2 to 0.25 on
the expiries under two weeks, a worst single miss of 1.7) and are nearly clean where the
market quotes, but the wings they extrapolate imply negative densities and crossing slices
on thousands of grid points. The replication integral reads those wings, and the free fit
gives the 30-day vol furthest from the CBOE recipe on the same chain (16.03 against
15.31). Adding penalties, the approach taken by the open-source SVI calibrators this
project started from, removes most of the wing arbitrage but moves calendar violations
inside the quoted range. SSVI is arbitrage-free by theorem. eSSVI is
butterfly-free by construction and calendar-clean on this chain, but its calendar
constraints are necessary only, and on the historical panels below it crosses on about
a quarter to half of the sessions. Both cost about two vol points of fit: eSSVI misses
by 2 to 4 points out to one month, about one point at three to six months and under half a
point at one year. Every constrained model, penalised SVI included, misses its worst quote
by about 20 points. One SSVI shape per expiry cannot follow the curvature of a short-dated
smile, and the sufficient butterfly condition it is held to is tight when total variance
is small, which flattens the one-week skew further; how much of the gap each explains is
not separated here.

![Market bid-ask against the free SVI and eSSVI fits at one week, one month and six months](docs/smile.png)

The chart shows where eSSVI pays for being arbitrage-free: at one week and one month it
sits up to 14 vol points under the deep out-of-the-money puts, the strikes a crash hedge
is bought at. An average error of two points hides that; the picture does not. The free
SVI follows those puts, then turns sharply upward in the call wing it has no quotes for.

### The premium: what selling that volatility has earned

A 30-day variance swap struck at every VIX close from 1990, settled on the next 21 trading
days of S&P 500 returns, sampled every 21 days so that windows do not overlap: 440
windows. P&L per unit of vega notional, `(K² − RV) / 2K`, in vol points.

| Statistic | Value |
| --- | --- |
| Mean VIX / mean realized vol | 19.4% / 15.3% |
| Windows with VIX above realized | 84.3% |
| Mean / median seller P&L | 2.72 / 3.91 |
| Worst window | −88.9 |
| Annualised Sharpe | 1.19 |
| Skewness | −6.17 |

These numbers are for windows starting on the first day of the sample. The median
across the 21 possible starting days is a Sharpe of 1.06 and a worst window of −120.

The premium is real and it is not free money: the seller wins five windows in six, and
the worst window takes back almost three years of average gains. The choice of sampling
day is not innocent either: across the 21 possible phases the mean P&L only moves from
2.44 to 2.89, but the Sharpe ranges from 0.59 to 1.25 and the worst window from −66 to
−252. In 20 phases out of 21 that worst window is the COVID crash, and its size depends
only on whether the swap was struck in mid-February 2020, with the VIX still low, or in
early March, after it had already risen.

Regressed in variance, realized on VIX squared gives a slope of **1.01** (White standard
error 0.17) and an intercept of **−0.011** (0.006), R² 0.40. The data cannot reject a
slope of one: VIX squared moves one for one with the variance that follows, shifted up by
a roughly constant premium, rather than over-reacting when volatility is high. The wide
standard error is the honest part of that sentence, and the intercept is itself only
borderline significant (t ≈ −2).

Full report with term structure, parity forwards, the quote ledger and regimes:
[`reports/options.html`](reports/options.html).

## Method

- **Quotes to volatilities.** Forward and discount factor per expiry from put-call
  parity, `C − P = D(F − K)`, regressed on strikes near spot: no rate curve and no
  dividend forecast is assumed. The regression starts from Theil-Sen and trims pairs
  more than four robust deviations off the line, because a handful of stale quotes moves
  an OLS slope by more than the whole funding rate. Premiums are divided by *D* and
  inverted with Black-76 on the forward.
- **Every refused quote is counted.** In-the-money side, under seven days, no bid,
  crossed, spread above half the mid, beyond ±0.6 log-moneyness, last trade more than 30
  days old: each quote is either a volatility or a line in the ledger the report prints.
- **SVI per slice.** Raw SVI in volatility space, residuals scaled by the half spread.
  Started from the quasi-explicit grid of Zeliade (2009): for fixed `(m, σ)` the other
  three parameters solve a linear least squares, so a 2-D grid replaces a blind 5-D
  multi-start.
- **SVI + penalties.** The same fit with Durrleman and calendar penalties on the whole
  moneyness grid, tightened by continuation and started from the previous slice lifted to
  the current at-the-money variance. It is the baseline that open-source calibrators use,
  run here so its residual arbitrage can be measured rather than assumed away.
- **SSVI.** Gatheral-Jacquier power-law SSVI, three shared parameters and one
  at-the-money variance per expiry, constrained to their sufficient no-arbitrage region.
- **eSSVI.** One SSVI slice per expiry, fitted in maturity order in wing-slope
  coordinates `a = ψ(1+ρ)`, `b = ψ(1−ρ)`. Butterfly: `max(a, b) < 4` and
  `(a+b)·max(a, b) ≤ 8θ`. Calendar: `θ`, `a` and `b` non-decreasing. Linear interpolation in
  time preserves both, so the surface is clean between pillars too; the pipeline checks
  it on 400 interpolated maturities and the report prints the count (zero).
- **The VIX, rebuilt.** The CBOE white-paper recipe on the chain's quotes (stale ones dropped, zero bids kept for the
  recipe's truncation rule), with `e^{RT}` taken
  from the parity discount factor, and the continuous log-contract replication on each
  model's 30-day slice.
- **The premium.** Non-overlapping 21-day windows with sensitivity across all 21
  offsets, a Mincer-Zarnowitz regression in variance terms with White (HC0) errors, and
  results by VIX regime.

### Built on

- [`py_lets_be_rational`](https://github.com/vollib/py_lets_be_rational) (MIT), Peter
  Jäckel's "Let's Be Rational" (2015): implied volatility to machine precision in two
  Householder steps, instead of the Newton-plus-bisection loop most open-source pricers
  carry, which fails silently in the wings where vega vanishes.
- Zeliade Systems, *Quasi-explicit calibration of Gatheral's SVI model* (2009).
- Gatheral and Jacquier, *Arbitrage-free SVI volatility surfaces* (2014); Hendriks and
  Martini, *The extended SSVI volatility surface* (2019).
- CBOE, *VIX White Paper*.
- Open-source SVI calibrators on GitHub for the penalised baseline. Code under copyleft
  licences (AGPL) was read for ideas only; none of it is copied here.

### Data sources

- **2026 capture**: Yahoo Finance via `yfinance`, frozen in `data/raw/`.
- **SPX/SPXW closes, 2022H2**: end-of-day chains from
  [HistoricalData.net](https://historicaldata.net/options.html), free sample, used under
  its licence, which requires this credit and forbids redistributing the data. Only
  per-session aggregates (`data/panel/`) are committed; `scripts/fetch_eod_sample.py`
  downloads the files.
- **SPY closes, 2008-01-02 to 2025-12-12**: the `data-v1` release of
  [lambdaclass/options_backtester](https://github.com/lambdaclass/options_backtester),
  which redistributes it "for research and educational reproducibility". It credits an
  upstream repository, philippdubach/options-data, announced as MIT but no longer online,
  and the data most likely comes from Alpha Vantage. The terms under which the original
  quotes may be reused are therefore not established; this project treats the archive as
  research input, commits only aggregates, and `scripts/fetch_spy_archive.py` downloads it
  from the release. Read with column and date filters, the 25-million-row file never has
  to fit in memory.
- **Three-month Treasury bill** for the SPY discount: FRED series
  [DTB3](https://fred.stlouisfed.org/series/DTB3), public domain, fetched by the same
  script.

## Limitations

Stated because they matter more than the headline numbers.

- **The headline is still one afternoon.** The tables at the top are the 2026-10-05
  capture. The panels below them turn its counts into distributions, but on other data:
  SPX closes from a bear market (2022, VIX mostly 20 to 35) and SPY closes up to
  2025-12-12. Nothing archived covers 2025-12-13 to the capture; the capture itself and
  the daily captures a server takes from 2026-10-06 are the only data for that stretch.
- **SPY is not SPX.** SPY options are American, settle into shares at the 16:00 close and
  pay through a fund that distributes dividends. Put-call parity does not hold for them:
  an in-the-money put sits on its exercise value, and the parity slope read on SPY closes
  gives discount factors from 1.005 to 1.04, which refused most sessions until the method
  changed. For SPY the discount is pinned to the three-month Treasury bill (FRED DTB3,
  one rate for every maturity up to a year) and the forward is read from strikes below
  spot, where the in-the-money leg is a call. Only out-of-the-money quotes enter the
  fits, and their small early-exercise premium is read as volatility. Maturities stop at
  one year, and dividends are absorbed by the forward. SPY trades at about a tenth of
  SPX, so its 30-day variance compares with the VIX, but the CBOE recipe run on SPY is an
  approximation of the index, not the index.
- **The SPY archive has no last-trade date.** The 30-day staleness filter cannot be
  applied, so stale quotes stay in the SPY panel; its arbitrage counts are an upper bound
  next to the SPX ones.
- **The two archives are one feed.** On the 127 sessions both cover, every SPY bid and ask
  is identical (see the cross-check below). The 2022 overlap is a check that the SPY
  adapter reads what it should, not an independent confirmation.
- **Delayed, and in places stale, quotes.** Yahoo serves 15-minute delayed quotes and
  leaves a contract's bid and ask as they stood at its last trade. Without the 30-day
  last-trade filter the chain shows 367 executable vertical and 594 butterfly arbitrages;
  with it, 0 and 15. The 30-day cutoff is a judgment call, not an estimate.
- **Short-dated rates are noise.** At one week a 0.1% error on the discount factor is a
  five-point error on the implied rate. The parity rate is 3.9–5.6% from three weeks out
  and up to 20% at seven days. It barely moves the undiscounted premium, which is what the
  volatility is read from, but the rate column should not be read as a funding curve.
- **The VIX check is not instantaneous.** The index is live and the quotes are delayed,
  so 15.31 against 15.57 mixes recipe error with fifteen minutes of market.
- **eSSVI's calendar condition is necessary, not sufficient.** Non-decreasing `θ`, `a`, `b`
  is required, not enough: with `θ` and `a` flat and `b` rising, the at-the-money slope
  `(a − b)/2` falls and the later slice dips below the earlier one just right of the money
  (`tests/test_svi.py` holds the counterexample). The fitted parameters on the failing
  sessions are monotone to machine precision, one root is kept per expiry (SPXW over SPX;
  SPY has a single root and no duplicate contracts), and the gaps are far above the
  1e-9 tolerance, so this is the model, not the fit, the audit or the data. It shows
  between expiries one to three days apart where `θ` sits at its floor: on 2022-08-15 the
  16-day slice is 7% below the 15-day one in total variance at k = 0.04. Counted over the
  panels, eSSVI has calendar violations on **19 of 33** HD sessions (inside the quoted
  range on 15, up to 922 grid points) and on **15 of 55** SPY quarterly sessions (quoted
  on 12, up to 299), about 1–4% of the grid between consecutive expiries. Butterfly stays
  at zero everywhere. On the 2026 capture the dense-grid check finds no crossing; that is a
  property of that chain, not a guarantee. A sufficient condition (Hendriks and Martini
  give one) would have to be imposed in the fit to close this.
- **Penalties do not guarantee freedom from arbitrage.** The penalised SVI keeps 596
  calendar violations inside the quoted range. That is a finding about the approach, and
  it is reported rather than tuned away.
- **The VIX is a 30-calendar-day contract settled here on 21 trading days.** The swap
  window is an approximation that ignores holidays and the exact 30-day horizon.
- **Closes are not simultaneous.** VIX settles at 16:15, the S&P 500 at 16:00.
- **VIX before 2003 is back-calculated.** The current methodology was introduced in 2003;
  earlier values were computed after the fact.
- **No transaction costs or margin on the swap.** A real seller pays a spread on entry and
  posts collateral that a −88.9 window would call.

## Running it

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m olab --output reports/options.html
```

The full surface run takes about four minutes. Inputs are the frozen captures in
`data/raw/`; `scripts/capture_chain.py` (during US market hours) and
`scripts/capture_history.py` take new ones, with `pip install -e ".[capture]"`.
`scripts/build_readme_chart.py` redraws the chart above.

The session panels need the archives, which are not in the repository (see Data sources):

```bash
pip install -e ".[archive]"
python scripts/fetch_eod_sample.py            # HistoricalData.net SPX/SPXW closes, 2022H2
python scripts/fetch_spy_archive.py           # SPY closes 2008-2025, about 600 MB
python scripts/run_panel.py --source hd --period W
python scripts/run_panel.py --source spy --period M
python scripts/cross_check_sources.py         # needs both
```

Each session takes two to three minutes, most of it in the penalised SVI, and the runner
resumes where it stopped. On a machine with other work running, set
`OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1`: the fits call small linear
algebra kernels many times, and a BLAS that spreads each call over every core made a
session three times slower here, not faster. The report picks up whichever panels exist
in `data/panel/`.

## Tests

```bash
.venv/bin/python -m pytest --cov=src/olab
```

The suite runs offline in under a minute. Unit tests check each piece against a known
answer: a Black chain priced with a given forward, discount and smile must come back out
of the parity regression and the inversion; a flat smile must replicate its own variance;
eSSVI must stay clean between its pillars. A regression test runs the full pipeline on a
frozen six-expiry subset of the chain (`tests/fixtures/`) and compares every number with
those it produced when frozen; `scripts/build_fixture.py` regenerates it after an intended
change.

## Related

Four companion studies, same method: a frozen capture, a rendered report, and a
limitations section longer than the results.

- [portfolio-lab](https://github.com/emiliensabathier/portfolio-lab) — whether any allocation rule beats a static 60/40
- [rates-lab](https://github.com/emiliensabathier/rates-lab) — what the yield curve prices: policy path, inflation, term premium
- [valuation-lab](https://github.com/emiliensabathier/valuation-lab) — what a share price already assumes, by inverting a DCF
- [credit-lab](https://github.com/emiliensabathier/credit-lab) — which default score flags first, against real credit events

## License

MIT.
