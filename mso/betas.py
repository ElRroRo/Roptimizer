"""Per-asset crash/rally jump betas and variance co-jump multipliers (#3, #9; owner's paper
"Beta Behavior in Jump Regimes", ODTU Econ400, draft 2).

Surprise days: days where the AR-GARCH(1,1) standardized residual of daily ^GSPC log returns (x100) is
beyond -3 (crash) or +3 (rally). Beta = mean asset log return on those days / mean S&P log return on them,
on daily data, each series on its own dates.
  - >= MIN_DAYS days in the asset's history: direct.
  - fewer, stock: the LOWESS curve normal beta -> crash (span 0.6) or rally (span 0.5) beta, fitted on the
    calibration pool's stocks and stored with the jump version (the paper's spans).
  - fewer, not a stock (ETF, future, fund): normal beta.
  - manual: library/beta_overrides.json, per ticker, outside the versions, always shown as manual.

Co-jump multiplier: an asset's own mean proportional rise in weekly GARCH conditional variance in the week
after an S&P crash week (weekly AR-GARCH residual below -3), relative to the pre-crash variance; the
simulator applies it to the asset's CURRENT variance. Fewer than 3 crash weeks: the pooled S&P value.

Per-ticker results are stored per version in jumpdb/<version>/tickers.json the first time a portfolio
uses the ticker; the LOWESS curves in jumpdb/<version>/lowess.json.
"""
import datetime as dt
import json
import os
import warnings

import numpy as np
import pandas as pd
from arch import arch_model

from mso import jumpdb
from mso.data import drop_incomplete_week

MIN_DAYS = 10
MIN_COJUMP_WEEKS = 3
LOWESS_SPAN = {"crash": 0.6, "rally": 0.5}
LOWESS_MIN_OBS = 2400            # the paper's sample filter: about 10 years of daily returns
LOWESS_MIN_DAYS = 3              # and at least 3 surprise days for a point
OVERRIDES_PATH = os.path.join(jumpdb.REPO, "library", "beta_overrides.json")
STOCK_TYPES = {"EQUITY"}


def _complete(s, interval):
    """Drop a bar still in progress: today's daily bar (New York date), or the current week's."""
    if interval == "1wk":
        return drop_incomplete_week(s, "1wk")
    if len(s):
        last = pd.Timestamp(s.index[-1])
        last = last.tz_convert("America/New_York") if last.tzinfo is not None else last
        if last.date() >= pd.Timestamp.now(tz="America/New_York").date():
            return s.iloc[:-1]
    return s


def _series(cache, ticker, interval):
    return _complete(cache.close(ticker, "max", interval, "history"), interval)


def _logret(s):
    s = s.dropna()
    if getattr(s.index, "tz", None) is not None:
        s.index = s.index.tz_localize(None)
    s.index = pd.to_datetime(s.index).normalize()
    s = s[~s.index.duplicated(keep="last")]
    return np.log(s / s.shift(1)).dropna()


def _garch_z(r, scale=100.0):
    warnings.filterwarnings("ignore")
    res = arch_model(r * scale, mean="AR", vol="GARCH").fit(disp="off")
    return res


def surprise_days(cache):
    """Daily ^GSPC log returns and its crash and rally surprise days."""
    b = _logret(_series(cache, "^GSPC", "1d"))
    z = _garch_z(b).std_resid.dropna()
    return b, z.index[z < -3], z.index[z > 3]


def _beta_on(a, b, days):
    d = days.intersection(a.index)
    if len(d) == 0:
        return None, 0
    return float(a.loc[d].mean() / b.loc[d].mean()), int(len(d))


def raw_betas(ticker, cache, market):
    """Normal, crash and rally beta of one ticker (each with its day count), before any fallback."""
    b, crash, rally = market
    a = _logret(_series(cache, ticker, "1d"))
    j = pd.concat([a, b], axis=1, join="inner").dropna()
    j.columns = ["a", "b"]
    if len(j) < 30:
        raise ValueError(f"{ticker}: only {len(j)} daily returns overlap the S&P 500, too few for a beta")
    normal = float(np.cov(j.a, j.b)[0, 1] / j.b.var())
    c, nc = _beta_on(j.a, j.b, crash)
    r, nr = _beta_on(j.a, j.b, rally)
    return dict(normal=normal, crash=c, crash_days=nc, rally=r, rally_days=nr, obs=int(len(j)),
                first=str(j.index[0].date()), last=str(j.index[-1].date()))


def quote_type(ticker):
    import yfinance as yf
    try:
        return (yf.Ticker(ticker).get_info() or {}).get("quoteType") or "UNKNOWN"
    except Exception:
        return "UNKNOWN"


# ------------------------------------------------------------------ LOWESS curves (per version)

def fit_lowess(points):
    """points: list of (normal, crash, crash_days, rally, rally_days, obs) for pool stocks.
    Returns {"crash": {"x": [...], "y": [...], "n": k}, "rally": ...}: the fitted curve at its sample's
    sorted normal betas, interpolated linearly (flat beyond the ends) when used."""
    from statsmodels.nonparametric.smoothers_lowess import lowess
    out = {}
    for side, col, ncol in (("crash", 1, 2), ("rally", 3, 4)):
        pts = [(p[0], p[col]) for p in points if p[col] is not None and p[ncol] >= LOWESS_MIN_DAYS and p[5] >= LOWESS_MIN_OBS]
        if len(pts) < 20:
            raise ValueError(f"LOWESS {side}: only {len(pts)} pool stocks qualify, need 20")
        x, y = np.array(pts).T
        fit = lowess(y, x, frac=LOWESS_SPAN[side], return_sorted=True)
        out[side] = dict(x=fit[:, 0].tolist(), y=fit[:, 1].tolist(), n=int(len(pts)), span=LOWESS_SPAN[side])
    return out


def lowess_curves(version, cache, market, progress=None):
    """The version's LOWESS curves, fitted on its pool's modelled stocks the first time they are needed."""
    path = os.path.join(version["path"], "lowess.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    with open(os.path.join(version["path"], "pool.json")) as f:
        pool = [t for t, s in json.load(f).items() if s.get("status") == "modelled"]
    points, failed = [], {}
    for i, t in enumerate(pool):
        try:
            r = raw_betas(t, cache, market)
            points.append((r["normal"], r["crash"], r["crash_days"], r["rally"], r["rally_days"], r["obs"]))
        except Exception as e:
            failed[t] = f"{type(e).__name__}: {e}"
        if progress:
            progress(i + 1, len(pool))
    curves = fit_lowess(points)
    curves.update(created=dt.datetime.now().isoformat(timespec="seconds"), pool_stocks=len(points), failed=failed,
                  surprise_days=dict(crash=int(len(market[1])), rally=int(len(market[2]))))
    with open(path, "w") as f:
        json.dump(curves, f, indent=1)
    return curves


def _on_curve(curve, x):
    return float(np.interp(x, curve["x"], curve["y"]))


# ------------------------------------------------------------------ co-jumps

def weekly_crash_weeks(cache):
    s = _logret(_series(cache, "^GSPC", "1wk"))
    z = _garch_z(s).std_resid.dropna()
    return z.index[z < -3]


def cojump_multiplier(ticker, cache, crash_weeks, pooled):
    """(multiplier, crash weeks used, source): the asset's own rise, or the pooled S&P value."""
    r = _logret(_series(cache, ticker, "1wk"))
    if len(r) < 104:
        return pooled, 0, "pooled"
    res = _garch_z(r)
    v = (res.conditional_volatility ** 2).dropna()
    rises = []
    pos = {d: i for i, d in enumerate(v.index)}
    for d in crash_weeks:
        i = pos.get(d)
        if i is None or i + 1 >= len(v) or v.iloc[i] <= 0:
            continue
        rise = v.iloc[i + 1] / v.iloc[i] - 1.0
        if np.isfinite(rise) and rise > 0:
            rises.append(rise)
    if len(rises) < MIN_COJUMP_WEEKS:
        return pooled, len(rises), "pooled"
    return float(np.mean(rises)), len(rises), "own"


# ------------------------------------------------------------------ overrides

def load_overrides():
    try:
        with open(OVERRIDES_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def set_override(ticker, crash=None, rally=None):
    """Manual betas for a ticker (None clears that side; both None removes the ticker)."""
    o = load_overrides()
    if crash is None and rally is None:
        o.pop(ticker, None)
    else:
        o[ticker] = dict(crash=crash, rally=rally, set=dt.datetime.now().isoformat(timespec="seconds"))
    os.makedirs(os.path.dirname(OVERRIDES_PATH), exist_ok=True)
    tmp = OVERRIDES_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(o, f, indent=1)
    os.replace(tmp, OVERRIDES_PATH)
    return o


# ------------------------------------------------------------------ per-ticker table

def ticker_table(tickers, version, cache, progress=None):
    """Crash/rally betas and co-jump multipliers for `tickers` under `version`, computed on first use and
    stored in the version's tickers.json; manual overrides applied on top. Returns {ticker: row}."""
    path = os.path.join(version["path"], "tickers.json")
    try:
        with open(path) as f:
            stored = json.load(f)
    except (OSError, ValueError):
        stored = {}
    need = [t for t in tickers if t not in stored]
    if need:
        market = surprise_days(cache)
        crash_weeks = weekly_crash_weeks(cache)
        pooled = float(version["cojump_config"]["var_jump_mult"])
        curves = None
        for t in need:
            r = raw_betas(t, cache, market)
            r["type"] = quote_type(t)
            stock = r["type"] in STOCK_TYPES
            for side in ("crash", "rally"):
                if r[side] is not None and r[f"{side}_days"] >= MIN_DAYS:
                    r[f"{side}_beta"], r[f"{side}_source"] = r[side], "direct"
                elif stock:
                    curves = curves or lowess_curves(version, cache, market, progress)
                    r[f"{side}_beta"], r[f"{side}_source"] = _on_curve(curves[side], r["normal"]), "LOWESS"
                else:
                    r[f"{side}_beta"], r[f"{side}_source"] = r["normal"], "normal"
            m, n, src = cojump_multiplier(t, cache, crash_weeks, pooled)
            r.update(cojump=m, cojump_weeks=n, cojump_source=src,
                     computed=dt.datetime.now().isoformat(timespec="seconds"), data_day=cache.day)
            stored[t] = r
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(stored, f, indent=1)
        os.replace(tmp, path)
    over = load_overrides()
    out = {}
    for t in tickers:
        row = dict(stored[t])
        for side in ("crash", "rally"):
            v = (over.get(t) or {}).get(side)
            if v is not None:
                row[f"{side}_beta"], row[f"{side}_source"] = float(v), "manual"
        out[t] = row
    return out


def print_table(table):
    """The fail-loudly printout: every asset's betas and co-jump with where each came from."""
    print(f"  {'ticker':<7} {'normal':>7} {'crash':>7} {'(days)':>7} {'source':<7} {'rally':>7} {'(days)':>7} "
          f"{'source':<7} {'co-jump':>8} {'source':<7}")
    for t, r in table.items():
        print(f"  {t:<7} {r['normal']:7.2f} {r['crash_beta']:7.2f} {r['crash_days']:>7} {r['crash_source']:<7} "
              f"{r['rally_beta']:7.2f} {r['rally_days']:>7} {r['rally_source']:<7} {r['cojump']:8.2f} {r['cojump_source']:<7}")


def market_vol_path(cache, steps):
    """The S&P 500's weekly volatility forecast over the horizon (log-return units), from an AR-GARCH(1,1)
    on its complete weekly bars: what a systematic jump in z-score units is multiplied by (#9)."""
    r = _logret(_series(cache, "^GSPC", "1wk"))
    res = _garch_z(r)
    var = res.forecast(horizon=steps, reindex=False).variance.values[-1]      # in (x100)^2 units
    return (np.sqrt(var) / 100.0).tolist()
