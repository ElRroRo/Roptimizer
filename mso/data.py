"""Market data: weekly return panels, prices and the shifted VIX regressor."""
# ==============================================================================
# PROJECT: Roptimizer
# AUTHOR: Eljon Rrodhe (eljonrrodhe11@gmail.com)
# COPYRIGHT: © 2026 Eljon Rrodhe
# LICENSE: Apache License 2.0 (see the LICENSE file)
# ==============================================================================

import re

import numpy as np
import pandas as pd
import yfinance as yf

from mso import cache


def _coverage_report(returns):
    """Per-ticker history coverage (first/last valid date and observation count)."""
    recs = []
    for c in returns.columns:
        s = returns[c].dropna()
        recs.append({
            "ticker": c,
            "obs": int(s.shape[0]),
            "start": (s.index.min() if len(s) else pd.NaT),
            "end": (s.index.max() if len(s) else pd.NaT),
        })
    return pd.DataFrame(recs).set_index("ticker")


def _print_coverage(report, min_obs):
    print("   Per-ticker history coverage:")
    for t, row in report.iterrows():
        flag = "  <-- THIN" if row["obs"] < min_obs else ""
        print(f"     {t:<8} obs={row['obs']:>5}  {str(row['start'])[:10]} -> {str(row['end'])[:10]}{flag}")


def drop_incomplete_week(data, interval="1wk"):
    """Drop yfinance's last weekly bar while its week is still in progress.

    Weekly bars are labelled with the week's first day, and yfinance returns the current week
    week-to-date, so on a Tuesday the last "weekly" return is two days long. Fitted as a full week
    it understates the latest variance, which seeds every forecast."""
    if interval != "1wk" or len(data) == 0:
        return data
    last = pd.Timestamp(data.index[-1])
    last = last.tz_localize(None) if last.tzinfo is not None else last
    if last.normalize() + pd.Timedelta(days=7) > pd.Timestamp.now().normalize():
        return data.iloc[:-1]
    return data


def _batch_close(stock_list, period, interval="1wk"):
    """Single batched yfinance download, normalised to a tickers-as-columns DataFrame.

    The batch `yf.download` already places every ticker on ONE shared weekly index
    (Monday-labelled, matching the VIX series used as the GARCH-X exog), which is what
    removes the BTC=F weekend-bar misalignment that the legacy per-ticker `.history()`
    loop produced. We deliberately do NOT relabel the grid (e.g. to W-FRI), as that would
    break the date alignment with the VIX exogenous regressor."""
    c = cache.active()
    if c is not None:
        # Through the day cache, one ticker at a time; the outer join is the same union grid a batch gives.
        raw = pd.concat({t: c.close(t, period, interval, "download") for t in stock_list}, axis=1)
    else:
        raw = yf.download(stock_list, period=period, interval=interval,
                          auto_adjust=True, progress=False)['Close']
    if isinstance(raw, pd.Series):
        raw = raw.to_frame(name=stock_list[0])
    raw = raw.reindex(columns=stock_list)
    raw.index = pd.to_datetime(raw.index)
    return drop_incomplete_week(raw, interval)


def history(ticker, period, interval):
    """yf.Ticker(ticker).history(...)["Close"], through the day cache when one is active."""
    c = cache.active()
    if c is not None:
        return c.close(ticker, period, interval, "history")
    return yf.Ticker(ticker).history(period=period, interval=interval)["Close"]


def last_prices(tickers):
    """Last valid close per ticker over the past 5 days (mixed schedules, e.g. BTC futures on weekends)."""
    c = cache.active()
    if c is not None:
        return [c.last_price(t)[0] for t in tickers]
    price_data = yf.download(tickers, period="5d", progress=False)['Close']
    return [price_data[t].dropna().iloc[-1] for t in tickers]


def ret_df(stock_list, period, interval="1wk", mode="max_info", min_obs=104, verbose=True):
    """
    Robust log-return panel builder.

    Downloads all tickers in ONE batch and aligns them onto a uniform weekly grid, so a
    single young/short asset (e.g. a recent IPO) or one trading on a different calendar
    (e.g. BTC=F over weekends) no longer collapses the usable sample via the legacy
    intersection-`.dropna()`.

    mode:
        'max_info'     : keep every asset's FULL history (panel may contain NaNs where an
                         asset did not yet trade). Downstream univariate GARCH uses each
                         asset's own window; correlation is estimated on the overlap with
                         PSD repair. RECOMMENDED. NOTE: callers must not blindly `.dropna()`.
        'intersection' : legacy behaviour - drop any row with a missing value.
        'drop_short'   : drop assets with < `min_obs` observations, then intersect.
        'cap_period'   : intersect, and report how far back a uniform window is feasible.

    :returns: pandas DataFrame of log returns (index = python dates).
    """
    prices = _batch_close(stock_list, period, interval)
    # Per ticker on its own dates: if a ticker's weekly rows do not line up with the shared grid, a
    # grid-wide shift(1) would divide by an empty row and silently erase its returns.
    returns = prices.apply(lambda c: np.log(c.dropna() / c.dropna().shift(1)))

    report = _coverage_report(returns)
    no_data = report.index[report["obs"] < 2].tolist()
    if no_data:
        # Fail loudly: an empty column would otherwise surface later as an obscure GARCH error.
        raise ValueError(f"No usable price history for {no_data} (unknown, delisted or mistyped ticker).")
    if verbose:
        print(f"\n   [ret_df] Requested period='{period}', interval='{interval}', mode='{mode}'.")
        _print_coverage(report, min_obs)

    if mode == "intersection":
        returns = returns.dropna(how="any")
    elif mode == "drop_short":
        keep = report.index[report["obs"] >= min_obs].tolist()
        dropped = [t for t in returns.columns if t not in keep]
        if dropped and verbose:
            print(f"   [drop_short] Dropping {dropped} (< {min_obs} obs).")
        returns = returns[keep].dropna(how="any")
    elif mode in ("cap_period",):
        common = returns.dropna(how="any")
        if verbose and len(common):
            print(f"   [cap_period] Uniform window feasible from {common.index.min()} "
                  f"({len(common)} obs).")
        returns = common
    elif mode == "max_info":
        returns = returns.dropna(how="all")
    else:
        raise ValueError(f"Unknown mode '{mode}'. Use max_info|intersection|drop_short|cap_period.")

    thin = report.index[report["obs"] < min_obs].tolist()
    if thin and mode in ("max_info", "intersection", "cap_period") and verbose:
        print(f"   [warn] Thin history (< {min_obs} obs): {thin}. "
              f"Their GARCH/Heston estimates will be lower confidence.")

    returns.index = pd.to_datetime(returns.index).date
    return returns


def price_df(stock_list, period, interval="1wk", mode="max_info"):
    """
    Creates a pandas DataFrame of (auto-adjusted) close prices using a single batched
    download on a uniform weekly grid. See ret_df for the `mode` semantics.

    :returns pandas dataframe with close prices
    """
    prices = _batch_close(stock_list, period, interval)
    if mode == "intersection":
        prices = prices.dropna(how="any")
    else:
        prices = prices.dropna(how="all")
    prices.index = pd.to_datetime(prices.index).date
    return prices


def get_shifted_vix(period="3y", interval="1wk", shift=4):
    """
    Retrieves VIX data for the given period plus additional weeks to account for shifting.

    :returns: A pandas Series with shifted VIX values and the latest VIX value.
    """

    def extend_period(period, shift, interval):
        """
        Dynamically extends the period to ensure enough data for shifting.
        Supports formats like '3y', '24mo', '6mo', '100d'.
        """
        match = re.match(r"(\d+)([ymd])", period)
        if not match:
            raise ValueError("Invalid period format. Use formats like '3y', '24mo', '6mo', '100d'.")

        value, unit = int(match.group(1)), match.group(2)

        if unit == "y":  # Convert years to months
            value *= 12
        elif unit == "d":  # Convert days to weeks (approximate)
            value //= 7  # Convert days to weeks for consistency with weekly interval

        # Add shift_weeks worth of extra data
        if interval == "1wk":
            value += (shift // 4)  # Convert weeks to months (approximate)
        elif interval == "1d":
            value += shift * 7  # Convert weeks to days
        elif interval == "1mo":
            value += (shift // 4)  # Add roughly 1 extra month if shift_weeks is 4

        # Convert back to proper format
        if unit == "y" or interval == "1mo":
            extended_period = f"{value}mo"
        elif unit == "d":
            extended_period = f"{value}d"
        else:
            extended_period = f"{value}mo"

        return extended_period

    # Dynamically extend the period
    extended_period = extend_period(period, shift, interval)

    # Fetch VIX data
    vix_data = drop_incomplete_week(
        history("^VIX", extended_period, interval), interval)

    # Shift the VIX data
    shifted_vix = vix_data.shift(shift).dropna()
    shifted_vix.index = pd.to_datetime(shifted_vix.index).date  # Ensure clean date formatting

    return shifted_vix, vix_data.iloc[-1:-5:-1]  # Also return the most recent VIX value
