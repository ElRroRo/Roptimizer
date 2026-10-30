# Is the production run's tail too mild? (2026-10-29)

Asked at the release sign-off: a 12-week 5% CVaR of about -8% looked low for a portfolio holding BTC=F.

Check: hold the production run's exact weights through history, every overlapping 12-week window, buy and
hold, weekly closes from the day cache, and measure the same statistics.

| 12 weeks, 5% tail | History 2022-03-07 to 2026-10-19 (242 weeks, IBHK as cash) | Simulated (A100, 3M held-out paths) |
|---|---|---|
| Volatility | 5.61% | 5.58% |
| CVaR | -7.31% | -7.94% |
| CDaR | -9.25% | -9.92% |
| Mean | +2.72% | +2.73% |
| Worst 12 weeks | -11.42% (from 2022-03-21) | |

On the window where every asset has history (2024-05-20 to 2026-10-19, 127 weeks, IBHK included):
history CVaR -5.66% and CDaR -8.22%, against the simulated -7.94% and -9.92%. Every single asset's
simulated tails are fatter than its own history (BTC=F CVaR -40.8% simulated, -26.7% historical).

Reading: the low portfolio tail is a property of the mix (about 64% in managed futures and short-duration
bonds, which held up in 2022), and the simulation is slightly more conservative than history.

## The equity section alone

Asked next: what are CVaR and CDaR for the equities only? Simulated on a fresh 2M-path laptop bank from the
production run's frozen inputs (it reproduces the whole portfolio's A100 figures: CVaR -7.94%, CDaR -9.93%);
history over 2021-10-25 to 2026-10-19 (261 weeks), every 12-week window.

| 12 weeks, 5% tail | Simulated | History |
|---|---|---|
| The production run's equity sleeve (19.2% of the portfolio; NRIM 23.2%, JPM 15.6%, FERG 14.2%, ADBE 13.6%, GOOGL 10.2%, SPGI 9.4%, META 7.0%, NVDA 4.8%, MNTS 1.9%) | vol 10.41%, CVaR -17.77%, CDaR -20.37% | vol 10.15%, CVaR -15.41%, CDaR -20.23%, worst -20.22% |
| The reference tree's Equities subportfolio (run 20261029-202008-ef5120) | vol 12.10%, CVaR -19.79%, CDaR -22.64% | vol 11.17%, CVaR -17.80%, CDaR -22.93%, worst -22.95% |
